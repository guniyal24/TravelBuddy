"""Specialist agents coordinated by the planner's supervisor step.

Each agent owns one concern and returns a small, inspectable result. They are deterministic
(rules and tools, no LLM) so their output is checkable and tested; the LLM planner only
composes the plan from what they prepared. The supervisor (TripPlanner._specialists) runs
StayAgent, FoodAgent and TransportAgent in parallel after research, and SafetyAgent reviews the
plan after the Critic accepts it.

  StayAgent       ranks stays by tier fit and the traveller's budget
  FoodAgent       applies the diet preference to eateries
  TransportAgent  road options from the origin and between destinations (get_transport tool)
  SafetyAgent     altitude / acclimatisation, high-altitude health, permits and advisories
"""
import re

from app.cost.pricing import parse_price_range
from app.towns import ELEVATION_M
from mcp_server.client import ToolError

# Approximate town elevations (m), used only when a stay has no measured elevation.
APPROX_ELEVATION_M = ELEVATION_M  # from the town registry
HIGH_TOWN_M = 2500
# Whole-word matches only, so "Barista" or "Fishtail Cafe" style names do not trip "bar"/"fish".
# Bars and pubs count too: a vegetarian traveller asking for veg food rarely wants one.
NON_VEG = re.compile(
    r"(?<![a-z])(non[- ]?veg|chicken|mutton|fish|meat|eggs?|kebabs?|kababs?|seekh|prawns?|"
    r"pork|beef|lamb|seafood|bar|pub|brewery|tavern)(?![a-z])")
VEG_WORDS = ("pure veg", "vegetarian", "veg only", "vegan", "jain")
BUDGET_SHARE_FOR_STAYS = 0.4  # of the traveller's total budget


def _text(e: dict) -> str:
    return f"{e.get('name', '')} {e.get('description', '')} {e.get('semantic_text', '')}".lower()


class StayAgent:
    @staticmethod
    def rank(req: dict, stays: list[dict]) -> tuple[list[dict], str]:
        budget = req.get("budget_inr")
        nights = max(1, (req.get("days") or 2) - 1)
        rooms = max(1, -(-(req.get("people") or 2) // 2))
        per_night = budget * BUDGET_SHARE_FOR_STAYS / nights / rooms if budget else None

        def key(e: dict):
            price = parse_price_range(e.get("price_text", ""))
            over = bool(per_night and price and sum(price) / 2 > per_night)
            return (over, e.get("tier") != req.get("tier"), not price)

        ranked = sorted(stays, key=key)
        dropped = sum(1 for e in ranked if key(e)[0])
        note = (f"{dropped} stay(s) listed above about ₹{round(per_night):,} per room-night "
                "were ranked lower for your budget." if per_night and dropped else "")
        return ranked, note


class FoodAgent:
    @staticmethod
    def filter(req: dict, meals: list[dict], diet: str) -> tuple[list[dict], str]:
        if not meals:
            return meals, ("No eateries are listed for this town in our data yet; ask your "
                           "stay or locals where to eat.")
        if diet != "veg":
            return meals, ""
        keep = [e for e in meals if not NON_VEG.search(_text(e))]
        keep.sort(key=lambda e: not any(w in _text(e) for w in VEG_WORDS))
        if not keep:  # never leave the planner with nothing: say so instead
            return meals, ("No eatery clearly suitable for vegetarians was found in the data; "
                           "confirm the menu before you go.")
        removed = len(meals) - len(keep)
        noun = "listing" if removed == 1 else "listings"
        return keep, (f"{removed} eatery {noun} mentioning meat, fish or a bar were left out "
                      "(based on listing text; confirm menus)." if removed else "")


class TransportAgent:
    def __init__(self, tools):
        self.tools = tools

    def _call(self, origin: str, dest: str, people: int) -> dict | None:
        try:
            r = self.tools.call("get_transport", origin=origin, destination=dest, people=people)
        except ToolError:
            return None
        return r if r.get("found") else None

    def brief(self, req: dict, destinations: list[str]) -> dict:
        people = req.get("people") or 1
        out: dict = {"to_first": None, "between": []}
        if req.get("origin"):
            out["to_first"] = self._call(req["origin"], destinations[0], people)
        for a, b in zip(destinations, destinations[1:], strict=False):
            leg = self._call(a, b, people)
            if leg:
                out["between"].append(leg)
        return out


class SafetyAgent:
    def __init__(self, tools):
        self.tools = tools

    def review(self, plan: dict, entities: dict, req: dict) -> dict:
        warnings: list[str] = []
        stops = []
        for d in plan["days"]:
            if d["day"] >= req["days"]:
                continue  # no night is spent after the last day
            stay = entities.get(d.get("stay") or "", {})
            elev = stay.get("elevation_m")
            if elev is None:
                elev = APPROX_ELEVATION_M.get(d["destination"])
            if elev is not None:
                stops.append({"day": d["day"], "name": stay.get("name") or d["destination"],
                              "sleep_elevation_m": float(elev)})
        vulnerable = bool(req.get("vulnerable_travellers"))
        altitude = []
        if len(stops) >= 1:
            try:
                res = self.tools.call("check_altitude_plan", stops=stops,
                                      vulnerable_travellers=vulnerable)
                altitude = res.get("issues", [])
            except ToolError:
                altitude = []
        warnings += [f"Altitude, day {i['day']}: {i['message']}" for i in altitude]
        high = [d for d in dict.fromkeys(x["destination"] for x in plan["days"])
                if APPROX_ELEVATION_M.get(d, 0) >= HIGH_TOWN_M]
        if vulnerable and high:
            names = ", ".join(h.removeprefix("destination_").replace("_", " ").title()
                              for h in high)
            warnings.append(f"Health: {names} is above {HIGH_TOWN_M} m. With children, elderly "
                            "travellers or heart/lung conditions, see a doctor first and carry "
                            "regular medicines.")
        advisories = []
        for dest in dict.fromkeys(d["destination"] for d in plan["days"]):
            try:
                adv = self.tools.call("check_conditions", place_id=dest, month=req["month"])
            except ToolError:
                continue
            for a in adv.get("advisories", []):
                name = dest.removeprefix("destination_").replace("_", " ").title()
                advisories.append({"destination": dest, "text": a["text"], "verify": a["verify"]})
                warnings.append(f"{name}: {a['text']} (confirm: {a['verify']})")
        return {"warnings": list(dict.fromkeys(warnings)), "altitude": altitude,
                "advisories": advisories}
