"""Turn an approved plan into a time-of-day timeline and map points. Deterministic, no LLM.

Times are a *suggested* rhythm (09:00 start, lunch about 13:00, dinner about 19:30), not
opening-hours-aware. Travel between stops is a straight-line estimate at hill-road speed.
"""
from math import ceil

from ingest.geo import haversine_km

START_MIN = 9 * 60
LUNCH_MIN = 13 * 60
DINNER_MIN = 19 * 60 + 30
CHECKIN_MIN = 17 * 60 + 30
STOP_MINUTES = {"Attraction": 90, "Activity": 120}
MEAL_MINUTES = 60
HILL_KMH = 25.0
DETOUR = 1.5  # roads are longer than the straight line


def hhmm(minutes: int) -> str:
    minutes = max(0, min(minutes, 24 * 60 - 1))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _pretty(dest_id: str) -> str:
    return dest_id.removeprefix("destination_").replace("_", " ").title()


def _item(kind: str, start: int, minutes: int, ent: dict | None, title: str, note: str = "") -> dict:
    return {"kind": kind, "time": hhmm(start), "end": hhmm(start + minutes),
            "id": (ent or {}).get("id"), "title": title, "note": note,
            "lat": (ent or {}).get("lat"), "lon": (ent or {}).get("lon")}


def _hop_minutes(a: dict | None, b: dict | None) -> tuple[int, str]:
    if not a or not b or None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return 20, ""
    km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) * DETOUR
    return max(15, ceil(km / HILL_KMH * 60)), f"about {km:.0f} km by road"


def build_timeline(plan: dict, entities: dict[str, dict], transfer_fn=None) -> dict:
    days_out, points = [], []
    prev_dest = None
    for d in plan["days"]:
        dest = d["destination"]
        items: list[dict] = []
        cursor = START_MIN
        if prev_dest and prev_dest != dest:
            info = transfer_fn(prev_dest, dest) if transfer_fn else None
            hours_hi = info["hours"][1] if info and info.get("found") else 2.0
            note = (f"about {info['distance_km']} km by road, roughly "
                    f"{info['hours'][0]:g}-{info['hours'][1]:g} hours (approximate)"
                    if info and info.get("found") else "allow 1-2 hours by road")
            items.append(_item("transfer", 8 * 60, ceil(hours_hi * 60),
                               None, f"Travel from {_pretty(prev_dest)} to {_pretty(dest)}", note))
            cursor = max(START_MIN, 8 * 60 + ceil(hours_hi * 60) + 30)
        meals = [entities[i] for i in d.get("meals") or [] if i in entities]
        stops = [entities[i] for i in d.get("stops") or [] if i in entities]
        lunch_done = False
        last = None
        for s in stops:
            if not lunch_done and meals and cursor >= LUNCH_MIN - 30:
                start = max(cursor, LUNCH_MIN)
                items.append(_item("meal", start, MEAL_MINUTES, meals[0], f"Lunch: {meals[0]['name']}"))
                cursor, lunch_done = start + MEAL_MINUTES, True
                last = meals[0]
            if last is not None and last is not s:
                hop, hop_note = _hop_minutes(last, s)
                cursor += hop
            dur = STOP_MINUTES.get(s.get("type"), 90)
            items.append(_item("stop", cursor, dur, s, s["name"],
                               f"{hop_note}" if last is not None and hop_note else ""))
            cursor += dur
            last = s
        if meals and not lunch_done:
            start = max(cursor, LUNCH_MIN)
            items.append(_item("meal", start, MEAL_MINUTES, meals[0], f"Lunch: {meals[0]['name']}"))
            cursor = start + MEAL_MINUTES
        stay = entities.get(d.get("stay") or "")
        if stay:
            items.append(_item("stay", max(cursor, CHECKIN_MIN), 30, stay,
                               f"Check in: {stay['name']}"))
            cursor = max(cursor, CHECKIN_MIN) + 30
        if len(meals) > 1:
            items.append(_item("meal", max(cursor, DINNER_MIN), MEAL_MINUTES, meals[1],
                               f"Dinner: {meals[1]['name']}"))
        items.sort(key=lambda x: x["time"])
        days_out.append({"day": d["day"], "destination": dest, "label": _pretty(dest),
                         "items": items})
        for order, it in enumerate(items, 1):
            if it["lat"] is not None and it["lon"] is not None:
                points.append({"day": d["day"], "order": order, "kind": it["kind"],
                               "title": it["title"], "lat": it["lat"], "lon": it["lon"],
                               "time": it["time"]})
        prev_dest = dest
    return {"days": days_out, "points": points,
            "note": "Suggested rhythm only. Check opening hours and allow extra time on hill "
                    "roads; travel times between stops are straight-line estimates."}
