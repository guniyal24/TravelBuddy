"""Render an approved plan as markdown, citing source ids."""
from datetime import date, timedelta


def day_date(request: dict, day: int) -> date | None:
    """The calendar date of a plan day, when the traveller gave a start date."""
    try:
        return date.fromisoformat(request["start_date"]) + timedelta(days=day - 1)
    except (KeyError, TypeError, ValueError):
        return None


def weather_line(w: dict | None) -> str:
    if not w or w.get("max_c") is None:
        return ""
    label = "forecast" if w.get("kind") == "forecast" else "typical for these dates, not a forecast"
    rain = w.get("rain_mm") or 0
    return (f"Weather: {round(w['min_c'])}-{round(w['max_c'])} °C, rain {rain:.0f} mm "
            f"({label})")


def _line(ent: dict | None, fallback: str, show_ids: bool = False) -> str:
    if not ent:
        return fallback
    extra = []
    if ent.get("price_text"):
        extra.append(ent["price_text"])
    if ent.get("hours"):
        extra.append(f"hours: {ent['hours']}")
    ident = f" [{ent['id']}]" if show_ids else ""
    return f"{ent['name']}{ident}" + (f" ({'; '.join(extra)})" if extra else "")


def render_itinerary(plan: dict, entities: dict[str, dict], cost: dict, warnings: list[str],
                     request: dict, show_ids: bool = False, weather: dict | None = None) -> str:
    by_day = {w["day"]: w for w in (weather or {}).get("days", [])}
    out = [f"# Your Uttarakhand trip: {request['days']} days, {request['people']} traveller(s)", ""]
    for d in plan["days"]:
        dest = d["destination"].removeprefix("destination_").replace("_", " ").title()
        when = day_date(request, d["day"])
        out.append(f"## Day {d['day']} - {dest}" + (f" · {when:%A %d %b}" if when else ""))
        if line := weather_line(by_day.get(d["day"])):
            out.append(f"_{line}_")
        for i in d.get("stops") or []:
            out.append(f"- Visit: {_line(entities.get(i), i, show_ids)}")
        for i in d.get("meals") or []:
            out.append(f"- Eat: {_line(entities.get(i), i, show_ids)}")
        if d.get("stay"):
            out.append(f"- Stay: {_line(entities.get(d['stay']), d['stay'], show_ids)}")
        out.append("")
    lo, hi = cost["total_inr"]
    out += [f"## Estimated cost: ₹{lo:,} - ₹{hi:,} total "
            f"(₹{cost['per_person_inr'][0]:,} - ₹{cost['per_person_inr'][1]:,} per person)", ""]
    for item in cost["items"]:
        tag = "" if item["source"] == "listing" else f" _({item['source']})_"
        out.append(f"- {item['label']}: ₹{round(item['low']):,} - ₹{round(item['high']):,}{tag}")
    out += ["", "_Excludes travel to Uttarakhand and any bookings. Lines marked 'assumption' use "
            "placeholder rates._", ""]
    if warnings:
        out += ["## Things to check", *[f"- {w}" for w in warnings], ""]
    out.append("_Distances are straight-line. Check road, weather and permit advisories before "
               "you travel._")
    return "\n".join(out)
