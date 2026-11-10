"""Multi-agent trip planner as a LangGraph state machine with human-in-the-loop steps.

  extract -> (missing details? -> ask_missing -> extract ...) -> options -> choose [HUMAN]
          -> research -> plan -> critic -> (errors -> plan, max N) -> cost -> approve [HUMAN]
          -> (edit -> plan | cancel -> END | approve -> finalize -> END)

Agents / roles
  Intake   (LLM)            turns free text into a structured request, asks for what is missing
  Advisor  (code + season)  proposes circuits for the month
  Research (retrieval)      pulls candidate places only from the knowledge base
  Planner  (LLM)            drafts the day-by-day plan, using ONLY candidate ids
  Critic   (deterministic)  rejects plans with unknown ids, missing stays, overloaded days
  Cost     (deterministic)  prices the plan with the cost engine

Human decisions use `interrupt()`; the run pauses (state kept by the checkpointer) and resumes
with `Command(resume=...)`, so a plan can wait for an answer for hours.
"""
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from app.booking.links import build_booking_links, render_links
from app.cost.pricing import parse_price_range
from app.graph.agents import (
    FoodAgent,
    SafetyAgent,
    StayAgent,
    TransportAgent,
)
from app.graph.concierge import HotelAgent, TravelInfoAgent
from app.graph.critic import fallback_plan, validate_plan
from app.graph.render import render_itinerary
from app.graph.schedule import build_timeline
from app.graph.trace import Tracer
from app.memory import TravelMemory, extract_preferences, trip_episode
from app.rag.retriever import RetrievalError
from mcp_server.client import LocalTools, ToolError

log = logging.getLogger(__name__)

OnEvent = Callable[[dict], None] | None
UNAVAILABLE_MSG = ("The places database is not responding right now, so I can't build a "
                   "reliable plan. Please try again in a minute.")


class PlanningUnavailable(Exception):
    """A data store the planner depends on is down. The run stops instead of producing an
    empty or made-up plan; the message is safe to show the traveller."""

MAX_ASKS = 2
MAX_PLAN_ATTEMPTS = 3
MAX_EDITS = 3
REQUIRED = ("days", "people", "month")

DESTINATIONS = {
    "destination_haridwar": {"name": "Haridwar", "lat": 29.9457, "lon": 78.1642,
                             "themes": ["temple", "pilgrim", "aarti", "ganga", "spiritual"]},
    "destination_rishikesh": {"name": "Rishikesh", "lat": 30.0869, "lon": 78.2676,
                              "themes": ["yoga", "rafting", "adventure", "cafe", "ashram",
                                         "meditation", "music"]},
    "destination_dehradun": {"name": "Dehradun", "lat": 30.3165, "lon": 78.0322,
                             "themes": ["food", "cafe", "shopping", "museum", "family"]},
    "destination_mussoorie": {"name": "Mussoorie", "lat": 30.4598, "lon": 78.0644,
                              "themes": ["hill", "honeymoon", "waterfall", "mall road", "views",
                                         "family", "snow"]},
    "destination_nainital": {"name": "Nainital", "lat": 29.3919, "lon": 79.4542,
                             "themes": ["lake", "boating", "hill", "honeymoon", "views", "family"]},
    "destination_jim_corbett": {"name": "Jim Corbett", "lat": 29.5300, "lon": 78.7747,
                                "themes": ["wildlife", "safari", "tiger", "nature", "jungle",
                                           "birding", "family"]},
    "destination_auli": {"name": "Auli", "lat": 30.5267, "lon": 79.5667,
                         "themes": ["ski", "snow", "skiing", "trek", "adventure", "views",
                                    "honeymoon"]},
    "destination_kedarnath": {"name": "Kedarnath", "lat": 30.7352, "lon": 79.0669,
                              "themes": ["pilgrim", "temple", "char dham", "chardham", "trek",
                                         "spiritual"]},
    "destination_badrinath": {"name": "Badrinath", "lat": 30.7433, "lon": 79.4938,
                              "themes": ["pilgrim", "temple", "char dham", "chardham",
                                         "spiritual"]},
    "destination_almora": {"name": "Almora", "lat": 29.5971, "lon": 79.6591,
                           "themes": ["culture", "heritage", "craft", "food", "views", "quiet"]},
    "destination_ranikhet": {"name": "Ranikhet", "lat": 29.6434, "lon": 79.4322,
                             "themes": ["quiet", "golf", "views", "hill", "nature", "family"]},
}

# How travellers write each town (English spellings, Hinglish, Devanagari). Matched in code, not
# by the LLM, so a town the traveller names is never lost or mistaken for an interest.
PLACE_ALIASES = {
    "destination_haridwar": ["haridwar", "hardwar", "हरिद्वार"],
    "destination_rishikesh": ["rishikesh", "hrishikesh", "ऋषिकेश"],
    "destination_dehradun": ["dehradun", "dehra dun", "doon", "देहरादून"],
    "destination_mussoorie": ["mussoorie", "mussorie", "masoori", "mussourie", "मसूरी"],
    "destination_nainital": ["nainital", "naini tal", "नैनीताल"],
    "destination_jim_corbett": ["jim corbett", "corbett", "जिम कॉर्बेट", "कॉर्बेट"],
    "destination_auli": ["auli", "औली"],
    "destination_kedarnath": ["kedarnath", "kedar nath", "केदारनाथ"],
    "destination_badrinath": ["badrinath", "badri nath", "बद्रीनाथ", "बदरीनाथ"],
    "destination_almora": ["almora", "अल्मोड़ा", "अल्मोडा"],
    "destination_ranikhet": ["ranikhet", "रानीखेत"],
}
_PLACE_RES = {d: re.compile("|".join(rf"(?<![a-z]){re.escape(a)}(?![a-z])" for a in aliases))
              for d, aliases in PLACE_ALIASES.items()}


def named_places(text: str) -> list[str]:
    """Destination ids the traveller named, in the order they appear in the text."""
    text = (text or "").lower()
    found = [(m.start(), d) for d, rx in _PLACE_RES.items() if (m := rx.search(text))]
    return [d for _, d in sorted(found)]


def _route_order(places: list[str]) -> list[str]:
    """Visit order for an ad-hoc circuit: start where the traveller started naming towns, then
    always go to the nearest town not yet visited (straight-line distance)."""
    from ingest.geo import haversine_km

    def km(a: str, b: str) -> float:
        return haversine_km(DESTINATIONS[a]["lat"], DESTINATIONS[a]["lon"],
                            DESTINATIONS[b]["lat"], DESTINATIONS[b]["lon"])

    route, rest = [places[0]], list(places[1:])
    while rest:
        nxt = min(rest, key=lambda p: km(route[-1], p))
        route.append(nxt)
        rest.remove(nxt)
    return route


def _says_from(text: str, place: str) -> bool:
    """True if the text names `place` as the starting point: "from X" or Hindi "X se"."""
    text = (text or "").lower()
    return any(re.search(rf"(?<![a-z])(from\s+{re.escape(a)}|{re.escape(a)}\s+(se|से))(?![a-z])",
                         text) for a in PLACE_ALIASES[place])


# Destinations the planner may offer: each needs at least one stay and two stops in the data.
# Auli and Kedarnath are in the data set but have too few listings; they join once enriched.
NOT_READY = {"destination_auli", "destination_kedarnath"}

# Sensible multi-stop circuits: (destinations in travel order, minimum days). Single-destination
# options are generated automatically for every destination.
CIRCUITS = [
    (["destination_haridwar", "destination_rishikesh"], 2),
    (["destination_dehradun", "destination_mussoorie"], 2),
    (["destination_rishikesh", "destination_mussoorie"], 3),
    (["destination_nainital", "destination_almora"], 3),
    (["destination_nainital", "destination_ranikhet", "destination_almora"], 4),
    (["destination_jim_corbett", "destination_nainital"], 3),
    (["destination_rishikesh", "destination_auli"], 4),
    (["destination_kedarnath", "destination_badrinath"], 5),
]

EXTRACT_SYSTEM = (
    "Extract trip details from the traveller's message. Return JSON only with keys: "
    '"origin" (city or null), "days" (int or null), "people" (int or null), "month" (1-12 or '
    'null), "tier" ("budget"|"mid"|"premium" or null), "budget_inr" (number or null), '
    '"interests" (list of short words), "vulnerable_travellers" (true if children, elderly or '
    'health conditions are mentioned, else false), "diet" ("veg"|"non-veg" or null), '
    '"pace" ("relaxed"|"balanced"|"packed" or null), "language" ("en" for English, "hi" for '
    'Hindi in Devanagari, "hinglish" for Hindi written in Latin letters). Use null when not '
    'stated; never guess (language is always one of the three).'
)

PLAN_SYSTEM = (
    "You are a trip planner for Uttarakhand. Build a day-by-day plan using ONLY the candidate "
    "ids provided. Return JSON only: "
    '{"days":[{"day":1,"destination":"<destination id>","stops":["A1"],"meals":["M1"],'
    '"stay":"S1 or null"}]}. Rules: exactly the requested number of days; max 3 stops and '
    "2 meals per day; stops are Attraction/Activity ids, meals are Eatery ids; every day "
    "except the last needs a stay id from that day's destination; stops and meals must also "
    "come from that day's destination (if it has no eateries, leave meals empty); do not "
    "repeat a stop; keep each day's stops in one area."
)


RESET = "__reset__"


def _collect(old: list | None, new) -> list:
    """Reducer for parallel hotel agents: each appends its town; RESET starts a new round."""
    if new == RESET:
        return []
    return [*(old or []), *(new or [])]


class TripState(TypedDict, total=False):
    user_text: str
    request: dict
    missing: list[str]
    asks: int
    options: list[dict]
    destinations: list[str]
    candidates: dict
    entities: dict
    plan: dict
    errors: list[str]
    warnings: list[str]
    feedback: str
    plan_attempts: int
    edits: int
    cost: dict
    decision: dict
    final: str
    owner: str  # account that started the trip (kept in durable state)
    preview: str  # localised itinerary shown for approval (computed once, reused at the end)
    approve_msg: str
    choose_msg: str
    profile: dict  # the traveller's saved preferences (long-term memory)
    agent_notes: list[str]
    transport: dict
    safety: dict
    timeline: dict
    locked_days: list[dict]  # days kept as-is during a mid-trip re-plan
    replan_from: int
    structured: dict
    status: str  # running | done | cancelled
    # Concierge stage (after approval)
    hotel_findings: Annotated[list, _collect]  # one entry per overnight town, in parallel
    travel: dict  # web-search travel notes
    concierge: dict  # ranked hotels per town + travel notes, shown for the hotel choice
    hotels_msg: str
    hotel_choice: dict  # {destination id: chosen stay id}
    # Long-term memory
    memories: list  # recalled at intake: preferences and past-trip episodes
    said: list  # everything the traveller typed this trip (the memory agent learns from it)
    learned: list  # preferences saved after approval


class TripPlanner:
    def __init__(self, llm, retriever, store, small_model: str, big_model: str,
                 checkpointer=None, tools=None, concierge: bool = False,
                 memory: TravelMemory | None = None):
        self.llm, self.retriever, self.store = llm, retriever, store
        self.concierge = concierge  # research hotels and travel info after approval
        self.memory = memory  # long-term memory across trips (None: off)
        self.small, self.big = small_model, big_model
        self.tools = tools or LocalTools()  # LocalTools (direct) or MCPTools (via MCP)
        self.graph = self._build(checkpointer or MemorySaver())

    def _season(self, place_id: str, month: int) -> dict:
        """Season check via the tool client; a tool failure degrades to 'unknown'."""
        try:
            return self.tools.call("check_season", place_id=place_id, month=month)
        except ToolError as exc:
            log.warning("check_season failed: %s", exc)
            return {"status": "unknown", "reasons": ["Season data unavailable right now."]}

    def _transfer(self, a: str, b: str) -> dict | None:
        """Road link between two destinations from the transport tool; None if unavailable."""
        try:
            return self.tools.call("get_transport", origin=a, destination=b)
        except ToolError as exc:
            log.warning("get_transport failed: %s", exc)
            return None

    def _loc(self, state: TripState, text: str) -> str:
        """Translate user-facing text into the traveller's language (Hindi / Hinglish).
        English, or any failure, returns the text unchanged."""
        lang = (state.get("request") or {}).get("language", "en")
        if lang not in ("hi", "hinglish") or not text:
            return text
        style = ("Hindi in Devanagari script" if lang == "hi"
                 else "Hinglish: Hindi written ONLY in Latin letters (never Devanagari)")
        try:
            out = self.llm.complete(self.small, [
                {"role": "system", "content": (
                    f"Translate the user's text into {style}. Keep markdown structure, URLs, "
                    "numbers, currency amounts, place names, hotel and restaurant names "
                    "exactly as written. Output only the translation.")},
                {"role": "user", "content": text}], max_tokens=3000)
        except Exception:
            log.exception("translation failed; using English")
            return text
        return out or text

    # ---------------- intake ----------------
    def _extract(self, state: TripState) -> TripState:
        profile = state.get("profile") or {}
        existing = {**{k: v for k, v in profile.items()
                       if k in ("tier", "interests", "vulnerable_travellers", "diet", "pace",
                                "language", "origin")},
                    **(state.get("request") or {})}
        res = self.llm.json(self.small, [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": state["user_text"]}], default={})
        merged = dict(existing)
        for key, val in res.items():
            if val not in (None, "", []):
                merged[key] = val
        for key in ("days", "people", "month"):
            try:
                merged[key] = int(merged[key]) if key in merged else None
            except (TypeError, ValueError):
                merged[key] = None
        if merged.get("month") and not 1 <= merged["month"] <= 12:
            merged["month"] = None
        if merged.get("days") is not None and not 1 <= merged["days"] <= 14:
            merged["days"] = None
        if merged.get("people") is not None and not 1 <= merged["people"] <= 20:
            merged["people"] = None
        # Towns named in this message (or, failing that, in an earlier one). Town names the LLM
        # put under interests are moved out, so they steer the circuit, not the search query.
        interests = [str(i) for i in merged.get("interests") or []]
        places = named_places(" ".join([state["user_text"], *interests]))
        merged["places"] = places or existing.get("places") or []
        merged["interests"] = [i for i in interests if not named_places(i)]
        # "Nainital, Ranikhet and Almora" is not a trip *from* Nainital. Keep a town that is also
        # a stop as the origin only when the text says so ("from Dehradun", "Dehradun se").
        origin_place = named_places(str(merged.get("origin") or ""))
        if origin_place and origin_place[0] in merged["places"]:
            if _says_from(state["user_text"], origin_place[0]):
                merged["places"] = [p for p in merged["places"] if p != origin_place[0]]
            else:  # a misread: fall back to the saved origin, unless that is the same town
                saved = existing.get("origin")
                merged["origin"] = saved if saved and saved != merged.get("origin") else None
        merged["tier"] = merged.get("tier") if merged.get("tier") in (
            "budget", "mid", "premium") else "budget"
        merged["language"] = merged.get("language") if merged.get("language") in (
            "en", "hi", "hinglish") else "en"
        merged["diet"] = merged.get("diet") if merged.get("diet") in ("veg", "non-veg") else ""
        merged["pace"] = merged.get("pace") if merged.get("pace") in (
            "relaxed", "balanced", "packed") else ""
        merged["vulnerable_travellers"] = bool(merged.get("vulnerable_travellers"))
        missing = [k for k in REQUIRED if not merged.get(k)]
        said = [*(state.get("said") or []), state["user_text"]]
        memories = state.get("memories")
        if memories is None:  # recall once per trip
            memories = self.memory.recall(state.get("owner", "")) if self.memory else []
        return {"request": merged, "missing": missing, "said": said, "memories": memories}

    def _route_after_extract(self, state: TripState) -> str:
        if state["missing"] and state.get("asks", 0) < MAX_ASKS:
            return "ask_missing"
        return "options"

    def _ask_missing(self, state: TripState) -> TripState:
        labels = {"days": "how many days", "people": "how many travellers",
                  "month": "which month you plan to travel"}
        answer = interrupt({
            "type": "ask",
            "message": self._loc(state, "To plan your trip I still need: "
                                 + ", ".join(labels[m] for m in state["missing"]) + "."),
            "missing": state["missing"]})
        return {"user_text": str(answer), "asks": state.get("asks", 0) + 1}

    # ---------------- advisor ----------------
    def _options(self, state: TripState) -> TripState:
        req = state["request"]
        if state["missing"]:  # asked enough; fall back to sensible defaults, say so
            req = {**req, "days": req.get("days") or 2, "people": req.get("people") or 2,
                   "month": req.get("month") or 11}
        days, month = req["days"], req["month"]
        interests = " ".join(req.get("interests", [])).lower()
        scored = []
        combos = [c for c, min_days in CIRCUITS
                  if days >= min_days and not NOT_READY.intersection(c)]
        combos += [[d] for d in DESTINATIONS if d not in NOT_READY]
        # The traveller named a set of towns no ready-made circuit covers (e.g. Ranikhet and
        # Almora): offer exactly those, in a sensible travel order, if there is a day for each.
        named = [d for d in req.get("places") or [] if d not in NOT_READY]
        if (len(named) >= 2 and days >= len(named)
                and not any(set(c) == set(named) for c in combos)):
            combos.append(_route_order(named))
        visited = {t for m in state.get("memories") or [] if m.get("kind") == "trip"
                   for t in m.get("towns") or []}
        for combo in combos:
            reasons, score = [], 0
            for d in combo:
                season = self._season(d, month)
                name = DESTINATIONS[d]["name"]
                score += {"good": 2, "ok": 1, "caution": 0, "unknown": 0}[season["status"]]
                if season["status"] == "caution":
                    reasons.append(f"{name}: {'; '.join(season['reasons'])}")
                score += sum(1 for t in DESTINATIONS[d]["themes"] if t in interests)
            if len(combo) > 1 and days >= 3:
                score += 1
            label = " + ".join(DESTINATIONS[d]["name"] for d in combo)
            seen = [d for d in combo if d in visited]
            if seen and not set(seen) & set(req.get("places") or []):
                score -= len(seen)  # gently prefer somewhere new, unless they asked for it
            scored.append({"id": "+".join(combo), "label": label, "destinations": combo,
                           "reasons": reasons, "score": score,
                           "visited": [DESTINATIONS[d]["name"] for d in seen]})
        # Towns the traveller named come first: most named towns covered, then fewest towns
        # they did not ask for, then season and interest fit.
        wanted = [d for d in req.get("places") or [] if d not in NOT_READY]
        scored.sort(key=lambda o: (-len(set(o["destinations"]) & set(wanted)),
                                   len(set(o["destinations"]) - set(wanted)) if wanted else 0,
                                   -o["score"]))
        msg = "Which circuit would you like?"
        unavailable = [DESTINATIONS[d]["name"] for d in req.get("places") or [] if d in NOT_READY]
        if unavailable:
            msg = (f"{' and '.join(unavailable)} can't be planned yet (not enough verified data). "
                   + msg)
        return {"request": req, "options": scored[:3],
                "choose_msg": self._loc({"request": req}, msg)}

    def _choose(self, state: TripState) -> TripState:
        picked = interrupt({"type": "choose",
                            "message": state.get("choose_msg") or "Which circuit would you like?",
                            "options": [{k: o.get(k) for k in ("id", "label", "reasons",
                                                               "visited")}
                                        for o in state["options"]]})
        match = next((o for o in state["options"] if o["id"] == picked), state["options"][0])
        return {"destinations": match["destinations"]}

    # ---------------- research ----------------
    def _research(self, state: TripState) -> TripState:
        req = state["request"]
        interest = " ".join(req.get("interests", []))
        specs = [("stops", ["Attraction", "Activity"], f"things to see and do {interest}", 14),
                 ("meals", ["Eatery"], f"good local food {interest}", 10),
                 ("stays", ["Stay"], f"{req['tier']} hotel to stay", 24)]

        def search(task):  # independent network calls: run them in parallel
            dest, (key, types, query, k) = task
            # strict: a search that keeps failing raises, instead of looking like "no results"
            hits = self.retriever.search(query, top_k=k, filter={
                "city": DESTINATIONS[dest]["name"], "type": {"$in": types}},
                strict=True, attempts=3)
            return dest, key, [h["id"] for h in hits]

        tasks = [(d, spec) for d in state["destinations"] for spec in specs]
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                found = list(pool.map(search, tasks))
        except RetrievalError as exc:
            raise PlanningUnavailable(UNAVAILABLE_MSG) from exc
        candidates, entities = {}, {}
        for dest in state["destinations"]:
            pools = {key: ids for d, key, ids in found if d == dest}
            ents = self.store.fetch_entities(sum(pools.values(), []))
            entities.update(ents)
            tier = req["tier"]
            stays = [ents[i] for i in pools["stays"] if i in ents]
            stays.sort(key=lambda e: (e.get("tier") != tier, e.get("price_text", "") == ""))
            candidates[dest] = {
                "stops": [ents[i] for i in pools["stops"] if i in ents][:8],
                "meals": [ents[i] for i in pools["meals"] if i in ents][:6],
                "stays": stays[:6]}
            # Every offered town has places and stays in the data, so finding neither means a
            # store failed. Never hand the traveller an empty plan.
            if not candidates[dest]["stops"] and not candidates[dest]["stays"]:
                log.error("research found nothing for %s; treating as an outage", dest)
                raise PlanningUnavailable(UNAVAILABLE_MSG)
        return {"candidates": candidates, "entities": entities}

    # ---------------- supervisor: specialist agents ----------------
    def _specialists(self, state: TripState) -> TripState:
        """Run the Stay, Food and Transport agents in parallel and merge their output."""
        req = state["request"]
        diet = req.get("diet", "")

        def stays():
            out, notes = {}, []
            for dest, pools in state["candidates"].items():
                ranked, note = StayAgent.rank(req, pools["stays"])
                out[dest] = ranked
                notes += [f"{DESTINATIONS[dest]['name']}: {note}"] if note else []
            return out, notes

        def food():
            out, notes = {}, []
            for dest, pools in state["candidates"].items():
                kept, note = FoodAgent.filter(req, pools["meals"], diet)
                out[dest] = kept
                notes += [f"{DESTINATIONS[dest]['name']}: {note}"] if note else []
            return out, notes

        def transport():
            return TransportAgent(self.tools).brief(req, state["destinations"])

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_stays, f_food, f_transport = (pool.submit(stays), pool.submit(food),
                                            pool.submit(transport))
            (ranked, n1), (kept, n2), brief = f_stays.result(), f_food.result(), f_transport.result()
        candidates = {d: {**p, "stays": ranked[d], "meals": kept[d]}
                      for d, p in state["candidates"].items()}
        return {"candidates": candidates, "transport": brief, "agent_notes": n1 + n2}

    # ---------------- planner ----------------
    def _plan(self, state: TripState) -> TripState:
        req = state["request"]
        # Short aliases (A1, M2, S1) instead of long entity ids: the model writes far fewer
        # tokens (faster) and makes fewer copying mistakes. Aliases map back to real ids.
        alias_to_id: dict[str, str] = {}
        counters = {"stops": 0, "meals": 0, "stays": 0}
        prefix = {"stops": "A", "meals": "M", "stays": "S"}
        lines = []
        for dest, pools in state["candidates"].items():
            lines.append(f"DESTINATION {dest}")
            for key in ("stops", "meals", "stays"):
                for e in pools[key]:
                    counters[key] += 1
                    alias = f"{prefix[key]}{counters[key]}"
                    alias_to_id[alias] = e["id"]
                    extra = f" | {e.get('tier')}" if e.get("tier") else ""
                    price = f" | {e['price_text']}" if e.get("price_text") else ""
                    lines.append(f"  {alias} | {e['name']} ({e['type']}){extra}{price}")
        user = (f"Traveller: {req['people']} people, {req['days']} days, month {req['month']}, "
                f"tier {req['tier']}, interests {req.get('interests') or 'none'}.\n"
                f"Destinations in order: {state['destinations']}\n\nCANDIDATES "
                "(use the short codes like A1, M2, S3 as ids):\n" + "\n".join(lines))
        prefs = [m["text"] for m in state.get("memories") or [] if m.get("kind") == "preference"]
        if prefs:
            user += ("\nRemembered about this traveller from earlier trips (follow these unless "
                     "this request says otherwise): " + "; ".join(prefs[:10]) + ".")
        pace = req.get("pace")
        if pace == "relaxed":
            user += "\nPace: relaxed. Use at most 2 stops per day."
        elif pace == "packed":
            user += "\nPace: packed. Use 3 stops per day where possible."
        if req.get("diet") == "veg":
            user += "\nThe traveller is vegetarian: choose meals accordingly."
        locked = state.get("locked_days") or []
        if locked:
            user += (f"\n\nDays 1 to {len(locked)} are already done and fixed; do not use their "
                     "stops again. Plan only the remaining days but still return all days in "
                     "order (the fixed days will be restored automatically).")
        if state.get("feedback"):
            user += f"\n\nFix these problems from the last attempt: {state['feedback']}"
        plan = self.llm.json(self.big, [{"role": "system", "content": PLAN_SYSTEM},
                                        {"role": "user", "content": user}], default={})
        plan = _apply_lock(_expand_aliases(plan, alias_to_id), locked)
        return {"plan": plan, "plan_attempts": state.get("plan_attempts", 0) + 1}

    # ---------------- critic ----------------
    def _critic(self, state: TripState) -> TripState:
        req = state["request"]
        centres = {d: (v["lat"], v["lon"]) for d, v in DESTINATIONS.items()}
        errors, warnings = validate_plan(
            state["plan"], state["entities"], req, self._season, centres,
            self._transfer)
        update: TripState = {"errors": errors, "warnings": warnings,
                             "feedback": "; ".join(errors)}
        if errors and state["plan_attempts"] >= MAX_PLAN_ATTEMPTS:
            plan = _apply_lock(fallback_plan(req, state["destinations"], state["candidates"]),
                               state.get("locked_days") or [])
            errors2, warnings2 = validate_plan(
                plan, state["entities"], req, self._season, centres, self._transfer)
            update = {"plan": plan, "errors": errors2, "feedback": "",
                      "warnings": [*warnings2, "The AI planner could not produce a valid plan, "
                                   "so a simple automatic plan was used."]}
        return update

    def _route_after_critic(self, state: TripState) -> str:
        if state["errors"] and state["plan_attempts"] < MAX_PLAN_ATTEMPTS:
            return "plan"
        return "safety"

    # ---------------- safety agent ----------------
    def _safety(self, state: TripState) -> TripState:
        res = SafetyAgent(self.tools).review(state["plan"], state["entities"], state["request"])
        warnings = list(dict.fromkeys([*state["warnings"], *res["warnings"]]))
        return {"safety": res, "warnings": warnings}

    # ---------------- cost ----------------
    @staticmethod
    def _stay_line(stay_id: str, nights: int, tier: str, ents: dict) -> dict:
        """A stay for the estimator. Without its own price, use the middle half of prices from
        other stays in the same destination that do have one (needs >= 3 of them)."""
        ent = ents[stay_id]
        line = {"nights": nights, "tier": tier, "price_text": ent.get("price_text", ""),
                "name": ent["name"]}
        if not line["price_text"]:
            prices = sorted(p for o in ents.values()
                            if o.get("type") == "Stay" and o.get("id") != stay_id
                            and o.get("destination_id") == ent.get("destination_id")
                            and (rng := parse_price_range(o.get("price_text", "")))
                            for p in [sum(rng) / 2])
            if len(prices) >= 3:
                lo, hi = prices[len(prices) // 4], prices[(3 * len(prices)) // 4]
                line["comparable_range"] = [round(lo), round(max(lo, hi))]
                line["comparable_note"] = (f"middle of {len(prices)} priced stays in "
                                           f"{DESTINATIONS.get(ent.get('destination_id'), {}).get('name', 'the area')}")
        return line

    def _cost(self, state: TripState) -> TripState:
        req, plan, ents = state["request"], state["plan"], state["entities"]
        nights: dict[str, int] = {}
        for d in plan["days"]:
            if d.get("stay") and d["day"] < req["days"]:
                nights[d["stay"]] = nights.get(d["stay"], 0) + 1
        stays = [self._stay_line(s, n, req["tier"], ents) for s, n in nights.items()
                 if s in ents]
        legs = []
        for prev, cur in zip(plan["days"], plan["days"][1:], strict=False):
            if prev["destination"] == cur["destination"]:
                continue
            info = self._transfer(prev["destination"], cur["destination"])
            if info and info.get("found"):
                f = info["fares"]
                legs.append({
                    "description": f"{DESTINATIONS[prev['destination']]['name']} to "
                                   f"{DESTINATIONS[cur['destination']]['name']} by road",
                    "fare_low": f["bus_per_person_inr"][0],
                    "fare_high": max(f["bus_per_person_inr"][1], f["taxi_per_person_inr"][1]),
                    "source": "assumption"})
        cost = self.tools.call("estimate_budget", people=req["people"], days=req["days"],
                               tier=req["tier"], stays=stays, legs=legs)
        warnings = list(state["warnings"])
        for note in state.get("agent_notes") or []:
            if note not in warnings:
                warnings.append(note)
        budget = req.get("budget_inr")
        if budget and cost["total_inr"][0] > budget:
            warnings.append(f"Estimated cost starts at ₹{cost['total_inr'][0]:,}, above your budget "
                            f"of ₹{int(budget):,}. Consider fewer days or a cheaper tier.")
        return {"cost": cost, "warnings": warnings}

    # ---------------- approval ----------------
    def _preview(self, state: TripState) -> TripState:
        """Build (and translate) the review text once. LangGraph re-runs an interrupting node
        from the top when it resumes, so slow work must not live inside the approve node."""
        text = render_itinerary(state["plan"], state["entities"], state["cost"],
                                state["warnings"], state["request"])
        return {"preview": self._loc(state, text), "timeline": self._timeline(state),
                "approve_msg": self._loc(state, "Approve this plan, or tell me what to change?")}

    def _approve(self, state: TripState) -> TripState:
        decision = interrupt({
            "type": "approve", "message": state["approve_msg"],
            "plan": state["plan"], "cost": state["cost"], "warnings": state["warnings"],
            "timeline": state["timeline"], "preview": state["preview"]})
        if isinstance(decision, str):
            decision = {"action": "edit", "text": decision}
        return {"decision": decision}

    def _route_after_approve(self, state: TripState) -> str:
        action = state["decision"].get("action")
        if action == "approve":
            return "concierge" if self.concierge else "finalize"
        if action == "cancel" or state.get("edits", 0) >= MAX_EDITS:
            return "cancel"
        return "edit"

    # ---------------- concierge (after approval) ----------------
    def _concierge(self, state: TripState) -> TripState:
        return {"hotel_findings": RESET, "travel": {}, "hotel_choice": {}}

    def _dispatch_concierge(self, state: TripState) -> list[Send]:
        """Fan out: one hotel agent per overnight town, plus the travel-info agent, all in
        parallel (LangGraph runs every Send of a step concurrently)."""
        req, plan = state["request"], state["plan"]
        nights: dict[str, dict] = {}
        for d in plan["days"]:
            if d["day"] < req["days"]:
                n = nights.setdefault(d["destination"], {"nights": 0, "current": d.get("stay")})
                n["nights"] += 1
        sends = []
        for dest, info in nights.items():
            town = DESTINATIONS[dest]
            stays = ((state.get("candidates") or {}).get(dest) or {}).get("stays") or []
            sends.append(Send("hotel_research", {
                "dest": dest, "town": {k: town[k] for k in ("name", "lat", "lon")},
                "stays": stays, "request": req, "current": info["current"],
                "nights": info["nights"]}))
        towns = [DESTINATIONS[d]["name"] for d in dict.fromkeys(x["destination"]
                                                                for x in plan["days"])]
        sends.append(Send("travel_info", {"towns": towns, "month": req.get("month")}))
        return sends

    def _hotel_research(self, payload: dict) -> TripState:
        found = HotelAgent(self.tools, self.llm, self.small).research(
            payload["dest"], payload["town"], payload["stays"], payload["request"],
            payload["current"])
        return {"hotel_findings": [{**found, "nights": payload["nights"]}]}

    def _travel_info(self, payload: dict) -> TripState:
        return {"travel": TravelInfoAgent(self.tools, self.llm, self.small).notes(
            payload["towns"], payload["month"])}

    def _rank_hotels(self, state: TripState) -> TripState:
        order = list(dict.fromkeys(d["destination"] for d in state["plan"]["days"]))
        towns = sorted(state.get("hotel_findings") or [],
                       key=lambda t: order.index(t["dest"]) if t["dest"] in order else 99)
        return {"concierge": {"towns": towns, "travel": state.get("travel") or {}},
                "hotels_msg": self._loc(state, "Here is what guests say about the hotels. Pick "
                                        "one for each town, or keep the ones in your plan.")}

    def _choose_hotels(self, state: TripState) -> TripState:
        towns = state["concierge"]["towns"]
        if not any(len(t["options"]) > 1 or t["options"] and t["options"][0]["reviews"]
                   for t in towns):
            return {"hotel_choice": {}}  # nothing to show or choose
        choice = interrupt({"type": "hotels", "message": state.get("hotels_msg"),
                            "towns": towns, "travel": state["concierge"]["travel"]})
        picks = choice.get("choices") if isinstance(choice, dict) else None
        return {"hotel_choice": picks if isinstance(picks, dict) else {}}

    def _apply_hotels(self, state: TripState) -> TripState:
        """Swap in the chosen hotels (only ones that were offered), then re-price and
        re-render the plan."""
        offered = {t["dest"]: {o["stay_id"] for o in t["options"]}
                   for t in state["concierge"]["towns"]}
        plan, changed = deepcopy(state["plan"]), False
        for d in plan["days"]:
            pick = (state.get("hotel_choice") or {}).get(d["destination"])
            if (d["day"] < state["request"]["days"] and pick in offered.get(d["destination"], ())
                    and pick != d.get("stay")):
                d["stay"], changed = pick, True
        if not changed:
            return {}
        warnings = [w for w in state["warnings"] if not w.startswith("Estimated cost starts")]
        new = {**state, "plan": plan, "warnings": warnings}
        cost = self._cost(new)
        new.update(cost)
        new["warnings"] = list(dict.fromkeys(new["warnings"]))
        return {"plan": plan, "cost": new["cost"], "warnings": new["warnings"],
                **self._preview(new)}

    def _edit(self, state: TripState) -> TripState:
        text = state["decision"].get("text", "")
        return {"feedback": f"Traveller asked: {text}",
                "said": [*(state.get("said") or []), text],
                "plan_attempts": 0, "edits": state.get("edits", 0) + 1}

    def _cancel(self, state: TripState) -> TripState:
        return {"status": "cancelled"}

    def _timeline(self, state: TripState) -> dict:
        return build_timeline(state["plan"], state["entities"], self._transfer)

    @staticmethod
    def _slim(ent: dict) -> dict:
        keys = ("id", "name", "type", "lat", "lon", "price_text", "hours", "tier",
                "elevation_m", "destination_id")
        out = {k: ent.get(k) for k in keys if ent.get(k) is not None}
        if ent.get("description"):
            out["description"] = ent["description"][:240]
        return out

    def _finalize(self, state: TripState) -> TripState:
        plan, ents, req = state["plan"], state["entities"], state["request"]
        english = render_itinerary(plan, ents, state["cost"], state["warnings"], req)
        links = build_booking_links(req, plan, ents)
        used = {i for d in plan["days"] for i in
                [*(d.get("stops") or []), *(d.get("meals") or []), d.get("stay")] if i}
        checklist = []
        for kind in ("flights", "trains", "buses", "stays"):
            for n, link in enumerate(links.get(kind, [])):
                checklist.append({"id": f"{kind}-{n}", "kind": kind, "done": False,
                                  "label": link["label"], "url": link["url"],
                                  "note": link["note"]})
        for n, text in enumerate(links.get("checklist", [])):
            checklist.append({"id": f"todo-{n}", "kind": "todo", "done": False, "label": text})
        links_md = render_links(links)
        if state.get("preview"):  # reuse the translated itinerary; only the booking part is new
            text = state["preview"] + "\n\n" + self._loc(state, links_md)
        else:
            text = self._loc(state, english + "\n\n" + links_md)
        structured = {
            "request": req, "plan": plan, "cost": state["cost"],
            "warnings": state["warnings"], "timeline": state.get("timeline") or self._timeline(state),
            "safety": state.get("safety", {}), "transport": state.get("transport", {}),
            "entities": {i: self._slim(ents[i]) for i in used if i in ents},
            "itinerary": text, "itinerary_en": english + "\n\n" + render_links(links),
            "checklist": checklist, "concierge": self._concierge_summary(state, plan)}
        return {"final": text, "structured": structured, "status": "done"}

    def _remember(self, state: TripState) -> TripState:
        """Memory agent, after approval only: lasting preferences from what the traveller
        typed (each kept with its exact quote) and one episode for this trip."""
        owner = state.get("owner", "")
        if not self.memory or not owner:
            return {"learned": []}
        prefs, _ = extract_preferences(self.llm, self.small, state.get("said") or [])
        learned = [m for p in prefs
                   if (m := self.memory.remember(owner, "preference", p["text"], p["quote"]))]
        edits = [s for s in (state.get("said") or [])[1:] if s]
        towns = list(dict.fromkeys(d["destination"] for d in state["plan"]["days"]))
        self.memory.remember(owner, "trip", trip_episode(state["request"], state["plan"], edits),
                             extra={"towns": towns, "month": state["request"].get("month")})
        return {"learned": learned}

    @staticmethod
    def _concierge_summary(state: TripState, plan: dict) -> dict:
        """What the saved trip keeps from the Concierge: per town the chosen hotel and the
        researched options (reviews trimmed), plus verified travel notes."""
        con = state.get("concierge") or {}
        if not con:
            return {}
        stays = {d["destination"]: d.get("stay") for d in plan["days"] if d.get("stay")}
        towns = []
        for t in con.get("towns", []):
            towns.append({"dest": t["dest"], "town": t["town"], "chosen": stays.get(t["dest"]),
                          "options": [{**o, "reviews": o["reviews"][:3]} for o in t["options"]],
                          "claims": t["claims"], "verified": t["verified"]})
        return {"towns": towns, "travel": con.get("travel") or {}}

    # ---------------- wiring ----------------
    def _build(self, checkpointer):
        g = StateGraph(TripState)
        for name, fn in (("extract", self._extract), ("ask_missing", self._ask_missing),
                         ("options", self._options), ("choose", self._choose),
                         ("research", self._research), ("specialists", self._specialists),
                         ("plan", self._plan), ("safety", self._safety),
                         ("critic", self._critic), ("cost", self._cost),
                         ("preview", self._preview), ("approve", self._approve), ("edit", self._edit),
                         ("cancel", self._cancel), ("finalize", self._finalize),
                         ("concierge", self._concierge), ("hotel_research", self._hotel_research),
                         ("travel_info", self._travel_info), ("rank_hotels", self._rank_hotels),
                         ("choose_hotels", self._choose_hotels),
                         ("apply_hotels", self._apply_hotels), ("remember", self._remember)):
            g.add_node(name, fn)
        g.add_edge(START, "extract")
        g.add_conditional_edges("extract", self._route_after_extract,
                                {"ask_missing": "ask_missing", "options": "options"})
        g.add_edge("ask_missing", "extract")
        g.add_edge("options", "choose")
        g.add_edge("choose", "research")
        g.add_edge("research", "specialists")
        g.add_edge("specialists", "plan")
        g.add_edge("plan", "critic")
        g.add_conditional_edges("critic", self._route_after_critic,
                                {"plan": "plan", "safety": "safety"})
        g.add_edge("safety", "cost")
        g.add_edge("cost", "preview")
        g.add_edge("preview", "approve")
        g.add_conditional_edges("approve", self._route_after_approve,
                                {"finalize": "finalize", "edit": "edit", "cancel": "cancel",
                                 "concierge": "concierge"})
        g.add_conditional_edges("concierge", self._dispatch_concierge,
                                ["hotel_research", "travel_info"])
        g.add_edge("hotel_research", "rank_hotels")
        g.add_edge("travel_info", "rank_hotels")
        g.add_edge("rank_hotels", "choose_hotels")
        g.add_edge("choose_hotels", "apply_hotels")
        g.add_edge("apply_hotels", "finalize")
        g.add_edge("edit", "plan")
        g.add_edge("finalize", "remember")
        g.add_edge("remember", END)
        g.add_edge("cancel", END)
        return g.compile(checkpointer=checkpointer)

    # ---------------- public API ----------------
    # Every entry point takes an optional `on_event` callback. With it, the graph is streamed and
    # each agent step is reported as it starts and finishes (see app/graph/trace.py).
    def start(self, thread_id: str, text: str, owner: str = "",
              profile: dict | None = None, on_event: OnEvent = None) -> dict[str, Any]:
        return self._run(
            {"user_text": text, "asks": 0, "plan_attempts": 0, "edits": 0, "status": "running",
             "owner": owner, "profile": profile or {}},
            thread_id, on_event)

    def replan(self, thread_id: str, from_day: int, reason: str,
               on_event: OnEvent = None) -> dict[str, Any]:
        """Change a finished trip from `from_day` on (bad weather, a cancelled bus, a change of
        mind). Earlier days are kept exactly; the rest is re-planned, re-validated and sent
        back for the traveller's approval like any other edit."""
        cfg = self._cfg(thread_id)
        snap = self.graph.get_state(cfg)
        vals = snap.values if snap else None
        if not vals or vals.get("status") != "done" or not vals.get("plan"):
            raise ValueError("Only an approved trip can be re-planned.")
        days = vals["request"]["days"]
        if not 1 <= from_day <= days:
            raise ValueError(f"from_day must be between 1 and {days}.")
        self.graph.update_state(cfg, {
            "feedback": f"The traveller needs a change from day {from_day} on: {reason}",
            "plan_attempts": 0, "edits": 0, "status": "running",
            "locked_days": [d for d in vals["plan"]["days"] if d["day"] < from_day],
            "replan_from": from_day, "said": [*(vals.get("said") or []), reason]},
            as_node="edit")
        return self._run(None, thread_id, on_event)

    def owner(self, thread_id: str) -> str | None:
        """Owner of a stored trip, or None if the trip does not exist."""
        snap = self.graph.get_state(self._cfg(thread_id))
        return snap.values.get("owner", "") if snap and snap.values else None

    def resume(self, thread_id: str, value: Any, on_event: OnEvent = None) -> dict[str, Any]:
        return self._run(Command(resume=value), thread_id, on_event)

    def _run(self, inp: Any, thread_id: str, on_event: OnEvent) -> dict[str, Any]:
        cfg = self._cfg(thread_id)
        if on_event is None:
            return self._result(self.graph.invoke(inp, cfg), thread_id)

        def emit(event: dict) -> None:  # a broken listener must never break the plan
            try:
                on_event(event)
            except Exception:
                log.exception("progress listener failed")

        tracer = Tracer(emit)
        for chunk in self.graph.stream(inp, cfg, stream_mode="tasks"):
            try:
                tracer.feed(chunk)
            except Exception:
                log.exception("could not describe a graph step")
        snap = self.graph.get_state(cfg)
        out = dict(snap.values)
        if snap.interrupts:
            out["__interrupt__"] = snap.interrupts
        return self._result(out, thread_id)

    @staticmethod
    def _cfg(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _result(self, out: dict, thread_id: str) -> dict[str, Any]:
        pending = out.get("__interrupt__")
        if pending:
            return {"status": "waiting", "prompt": pending[0].value}
        return {"status": out.get("status", "done"), "itinerary": out.get("final"),
                "state": out}


def _expand_aliases(plan: dict, alias_to_id: dict[str, str]) -> dict:
    """Replace short codes in the model's plan with real entity ids. Unknown codes are kept
    as written so the Critic reports them."""
    if not isinstance(plan, dict) or not isinstance(plan.get("days"), list):
        return plan
    def fix(v):
        return alias_to_id.get(v.strip(), v) if isinstance(v, str) else v
    days = []
    for d in plan["days"]:
        if not isinstance(d, dict):
            return plan
        days.append({**d, "stops": [fix(x) for x in d.get("stops") or []],
                     "meals": [fix(x) for x in d.get("meals") or []], "stay": fix(d.get("stay"))})
    return {**plan, "days": days}


def _apply_lock(plan: dict, locked: list[dict]) -> dict:
    """Restore the fixed (already travelled) days at the start of a plan."""
    if not locked or not isinstance(plan, dict) or not isinstance(plan.get("days"), list):
        return plan
    last = max(d["day"] for d in locked)
    rest = [d for d in plan["days"] if isinstance(d, dict) and d.get("day", 0) > last]
    return {**plan, "days": [*locked, *rest]}
