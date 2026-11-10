"""Readable progress events from the trip graph, for the live "agents at work" view.

LangGraph's `tasks` stream mode reports when each node starts and finishes, with the node's
input state and its update. This module turns those into small, display-ready events:

  {"id": task id, "node": "critic", "agent": "Critic", "phase": "start" | "end" | "wait",
   "message": "...", "details": ["..."], "tone": "info" | "ok" | "warn", "ms": 812}

Messages are built from the real state (counts, errors, prices), never canned text, so what the
traveller sees is what the agents actually did. Nothing here changes the plan.
"""
import time

from app.graph.critic import pretty

AGENTS = {
    "extract": "Intake", "ask_missing": "Intake", "options": "Advisor", "choose": "You",
    "research": "Research", "specialists": "Supervisor", "plan": "Planner", "critic": "Critic",
    "safety": "Safety", "cost": "Cost", "preview": "Writer", "approve": "You",
    "edit": "Planner", "cancel": "Planner", "finalize": "Booking",
}
# Nodes that pause for the traveller: their "start" is not shown (it repeats on resume).
HUMAN_NODES = {"ask_missing", "choose", "approve"}
START_MESSAGES = {
    "extract": "Reading your request",
    "options": "Scoring circuits against the season and your interests",
    "research": "Searching the knowledge base for places, food and stays",
    "specialists": "Stay, Food and Transport agents working in parallel",
    "critic": "Checking the draft: known places, stays, day load, season",
    "safety": "Checking altitude, health risks and advisories",
    "cost": "Pricing the plan with the cost engine",
    "preview": "Preparing the plan for your review",
    "finalize": "Building booking links and your checklist",
}
MAX_DETAILS = 4


def _names(dests: list[str]) -> str:
    return " + ".join(pretty(d) for d in dests)


def _inr(n) -> str:
    return f"₹{int(n):,}"


def _n(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _start(node: str, state: dict) -> str | None:
    if node == "plan":
        attempt = (state.get("plan_attempts") or 0) + 1
        if attempt == 1 and state.get("feedback"):
            return "Re-drafting the plan with your feedback"
        return ("Drafting a day-by-day plan" if attempt == 1
                else f"Re-drafting the plan (attempt {attempt}) to fix the Critic's notes")
    return START_MESSAGES.get(node)


def _end(node: str, state: dict, out: dict) -> tuple[str, list[str], str] | None:
    """(message, details, tone) for a finished node, or None to show nothing."""
    out = out or {}
    if node == "extract":
        req = out.get("request") or {}
        bits = [f"{req['days']} days" if req.get("days") else None,
                f"{req['people']} people" if req.get("people") else None,
                _month(req.get("month")), f"{req.get('tier')} tier" if req.get("tier") else None,
                req.get("diet") or None]
        details = []
        if req.get("interests"):
            details.append("Interests: " + ", ".join(req["interests"]))
        if req.get("origin"):
            details.append(f"Travelling from {req['origin']}")
        if req.get("language") in ("hi", "hinglish"):
            details.append("Replies will be in " + ("Hindi" if req["language"] == "hi"
                                                     else "Hinglish"))
        if out.get("missing"):
            details.append("Still missing: " + ", ".join(out["missing"]))
        return "Understood: " + " · ".join(b for b in bits if b), details, "info"
    if node == "options":
        opts = out.get("options") or []
        return (f"Shortlisted {_n(len(opts), 'circuit')}",
                [o["label"] + (" (season caution)" if o.get("reasons") else "") for o in opts],
                "info")
    if node == "choose":
        return f"You picked {_names(out.get('destinations') or [])}", [], "ok"
    if node == "research":
        cands = out.get("candidates") or {}
        n = {k: sum(len(p.get(k) or []) for p in cands.values()) for k in ("stops", "meals",
                                                                           "stays")}
        return (f"Found {n['stops']} places, {n['meals']} eateries and {n['stays']} stays "
                f"in {_n(len(cands), 'town')}",
                ["Only these listings may appear in your plan, so nothing is invented"], "info")
    if node == "specialists":
        details = []
        brief = out.get("transport") or {}
        for leg in [brief.get("to_first"), *(brief.get("between") or [])]:
            if leg:
                lo, hi = leg["hours"]
                origin = pretty(leg["origin"].removeprefix("city_"))
                details.append(f"Transport: {origin} to {pretty(leg['destination'])}, "
                               f"{leg['distance_km']} km, about {lo:g}-{hi:g} h by road")
        details += out.get("agent_notes") or []
        if not details:
            details.append("Stays ranked for your tier and budget; eateries matched to your diet")
        return "Specialist agents finished", details, "ok"
    if node == "plan":
        days = (out.get("plan") or {}).get("days")
        n = len(days) if isinstance(days, list) else 0
        return (f"Draft ready: {_n(n, 'day')}" if n else "The model returned an unusable draft",
                [], "info" if n else "warn")
    if node == "critic":
        errors = out.get("errors") or []
        warnings = out.get("warnings") or []
        if any("automatic plan was used" in w for w in warnings):
            return "Too many failed drafts: switched to the rule-based fallback plan", [], "warn"
        if errors:
            return (f"Rejected the draft: {_n(len(errors), 'problem')}, sending it back",
                    errors[:MAX_DETAILS], "warn")
        return (f"Approved the draft ({_n(len(warnings), 'note')} for you)" if warnings
                else "Approved the draft: every check passed", warnings[:MAX_DETAILS], "ok")
    if node == "safety":
        res = out.get("safety") or {}
        notes = res.get("warnings") or []
        if not notes:
            return "No altitude, health or advisory concerns", [], "ok"
        return f"{_n(len(notes), 'safety note')} added", notes[:MAX_DETAILS], "warn"
    if node == "cost":
        cost = out.get("cost") or {}
        total = cost.get("total_inr")
        if not total:
            return "Cost estimate ready", [], "info"
        return f"Estimated {_inr(total[0])} to {_inr(total[1])} in total", [
            "A range, not a quote: every line says if it is a listing price or an assumption"
        ], "info"
    if node == "preview":
        return "Plan ready for your review", [], "ok"
    if node == "approve":
        decision = out.get("decision") or {}
        action = decision.get("action")
        if action == "approve":
            return "You approved the plan", [], "ok"
        if action == "cancel":
            return "You cancelled the plan", [], "info"
        return "You asked for a change", [decision.get("text", "")][:1], "info"
    if node == "edit":
        return "Sending your feedback to the Planner", [], "info"
    if node == "cancel":
        return "Trip cancelled", [], "info"
    if node == "finalize":
        n = len((out.get("structured") or {}).get("checklist") or [])
        return f"Trip saved with a {n}-item booking checklist", [], "ok"
    return None


WAIT_MESSAGES = {"ask_missing": "Waiting for a few more details from you",
                 "choose": "Waiting for you to pick a circuit",
                 "approve": "Waiting for your approval"}


def _month(m) -> str | None:
    names = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
    return names[m - 1] if isinstance(m, int) and 1 <= m <= 12 else None


class Tracer:
    """Feed it LangGraph `tasks` chunks; it calls `emit` with display events."""

    def __init__(self, emit):
        self.emit = emit
        self._started: dict[str, tuple[float, dict]] = {}

    def feed(self, chunk: dict) -> None:
        node, task_id = chunk.get("name"), chunk.get("id")
        if node not in AGENTS:
            return
        base = {"id": task_id, "node": node, "agent": AGENTS[node]}
        if "input" in chunk:  # task started
            self._started[task_id] = (time.monotonic(), chunk.get("input") or {})
            msg = None if node in HUMAN_NODES else _start(node, chunk.get("input") or {})
            if msg:
                self.emit({**base, "phase": "start", "message": msg, "details": [],
                           "tone": "info"})
            return
        began, state = self._started.pop(task_id, (time.monotonic(), {}))
        ms = round((time.monotonic() - began) * 1000)
        if chunk.get("error"):
            self.emit({**base, "phase": "end", "message": "This step failed", "details": [],
                       "tone": "warn", "ms": ms})
            return
        if chunk.get("interrupts"):
            self.emit({**base, "phase": "wait", "message": WAIT_MESSAGES.get(node, "Waiting"),
                       "details": [], "tone": "info", "ms": ms})
            return
        ended = _end(node, state, chunk.get("result") or {})
        if ended:
            message, details, tone = ended
            self.emit({**base, "phase": "end", "message": message,
                       "details": [d for d in details if d][:MAX_DETAILS], "tone": tone,
                       "ms": ms})
