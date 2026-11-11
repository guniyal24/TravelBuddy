"""Turn an approved plan into a time-of-day timeline and map points. Deterministic, no LLM.

Times are a *suggested* rhythm (09:00 start, lunch about 13:00, dinner about 19:30). Where a
listing gives opening hours, stops that close early go first, a stop is not started before it
opens, and one that still cannot fit is flagged. Travel between stops is a straight-line
estimate at hill-road speed.
"""
import re
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


# "10AM", "8:15 AM", "5:30PM" or a 24-hour "09:00"
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b|\b(\d{1,2}):(\d{2})\b", re.I)


def parse_hours(text: str | None) -> tuple[int | None, int | None]:
    """Opening and closing minutes from a listing's free-text hours: the first time is the
    opening, the last the closing ("9AM-1PM and 2:30PM-5:30PM" is 09:00-17:30). (None, None)
    when there is nothing to go on ("24/7", "Annually"); "Closes 11:30 PM" gives only a close."""
    found = []
    for m in _TIME.finditer(text or ""):
        if m.group(4) is not None:
            h, mins = int(m.group(4)), int(m.group(5))
        else:
            h, mins = int(m.group(1)) % 12, int(m.group(2) or 0)
            h += 12 if m.group(3).lower() == "p" else 0
        if h < 24 and mins < 60:
            found.append(h * 60 + mins)
    if not found:
        return None, None
    if len(found) == 1:
        return (None, found[0]) if re.search(r"\bclos", text, re.I) else (found[0], None)
    open_, close = found[0], found[-1]
    return (open_, close) if close > open_ else (open_, None)  # past midnight: no limit


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


def build_timeline(plan: dict, entities: dict[str, dict], transfer_fn=None,
                   start_date: str | None = None, weather: dict | None = None) -> dict:
    from app.graph.render import day_date
    by_day = {w["day"]: w for w in (weather or {}).get("days", [])}
    days_out, points, warnings = [], [], []
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
        # places that close early first; the planner's order is kept otherwise (stable sort)
        stops.sort(key=lambda s: parse_hours(s.get("hours"))[1] or 24 * 60)
        lunch_done = False
        last = None
        for s in stops:
            if not lunch_done and meals and cursor >= LUNCH_MIN - 30:
                start = max(cursor, LUNCH_MIN)
                items.append(_item("meal", start, MEAL_MINUTES, meals[0], f"Lunch: {meals[0]['name']}"))
                cursor, lunch_done = start + MEAL_MINUTES, True
                last = meals[0]
            hop_note = ""
            if last is not None and last is not s:
                hop, hop_note = _hop_minutes(last, s)
                cursor += hop
            dur = STOP_MINUTES.get(s.get("type"), 90)
            opens, closes = parse_hours(s.get("hours"))
            if opens is not None and cursor < opens:
                cursor = opens  # do not arrive before it opens
            notes = [hop_note] if hop_note else []
            late = closes is not None and cursor + 30 > closes  # under 30 minutes before closing
            if late:
                notes.append(f"May be closed by then (hours: {s['hours']}); go earlier or "
                             "swap with another stop")
            elif closes is not None and cursor + dur > closes:
                dur = closes - cursor  # a shorter visit, ending at closing time
            item = _item("stop", cursor, dur, s, s["name"], "; ".join(notes))
            if late:
                item["late"] = True
                warnings.append(f"Day {d['day']}: {s['name']} may be closed by the time you "
                                f"get there (hours: {s['hours']}).")
            items.append(item)
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
        when = day_date({"start_date": start_date}, d["day"])
        days_out.append({"day": d["day"], "destination": dest, "label": _pretty(dest),
                         "date": when.isoformat() if when else None,
                         "weather": by_day.get(d["day"]), "items": items})
        for order, it in enumerate(items, 1):
            if it["lat"] is not None and it["lon"] is not None:
                points.append({"day": d["day"], "order": order, "kind": it["kind"],
                               "title": it["title"], "lat": it["lat"], "lon": it["lon"],
                               "time": it["time"]})
        prev_dest = dest
    return {"days": days_out, "points": points, "warnings": warnings,
            "note": "Suggested rhythm only. Check opening hours and allow extra time on hill "
                    "roads; travel times between stops are straight-line estimates."}
