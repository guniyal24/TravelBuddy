"""Assisted booking: search shortcuts and a checklist. The traveller pays on the official
sites; this module never handles payment or passenger details and does not claim live
fares, availability or bus timings (none are available from a free, permitted source)."""
from urllib.parse import quote_plus

from app.towns import KUMAON, STATIONS
from app.transport.routes import transport_options

# Origin city -> IATA code (major metros only; others fall back to a plain search link).
IATA = {"delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM", "bengaluru": "BLR",
        "bangalore": "BLR", "kolkata": "CCU", "chennai": "MAA", "hyderabad": "HYD",
        "pune": "PNQ", "ahmedabad": "AMD", "jaipur": "JAI", "lucknow": "LKO"}
JOLLY_GRANT = ("DED", "Dehradun (Jolly Grant) Airport")
PANTNAGAR = ("PGH", "Pantnagar Airport")
# Stations and the Kumaon/Garhwal split come from the town registry (curated, unverified).


def _airport(dest: str) -> tuple[str, str]:
    return PANTNAGAR if dest in KUMAON else JOLLY_GRANT


def _maps_search(name: str, city: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{name} {city}")


def build_booking_links(request: dict, plan: dict, entities: dict[str, dict]) -> dict:
    origin = (request.get("origin") or "").strip()
    first_dest = plan["days"][0]["destination"]
    city = first_dest.removeprefix("destination_").replace("_", " ").title()
    links: dict[str, list[dict]] = {"flights": [], "trains": [], "buses": [], "stays": []}

    ap_code, ap_name = _airport(first_dest)
    code = IATA.get(origin.lower())
    if code:
        q = quote_plus(f"Flights from {code} to {ap_code}")
        links["flights"].append({
            "label": f"{origin} to {ap_name}",
            "url": f"https://www.google.com/travel/flights?q={q}",
            "note": f"Compare fares and dates. {ap_name} is the nearest airport with regular "
                    f"flights to {city}; plan a road transfer."})

    st_code, st_name = STATIONS.get(first_dest, ("", city))
    if origin:
        links["trains"].append({
            "label": f"{origin} to {st_name}" + (f" ({st_code})" if st_code else ""),
            "url": "https://www.irctc.co.in/nget/train-search",
            "note": "Search on IRCTC with these stations and your date. Station code is "
                    "unverified; confirm it on IRCTC."})
        road = transport_options(origin, first_dest, request.get("people") or 1)
        road_note = ""
        if road.get("found"):
            lo, hi = road["hours"]
            road_note = (f"About {road['distance_km']} km by road, roughly {lo:g}-{hi:g} hours "
                         "(approximate). ")
        links["buses"].append({
            "label": f"Bus {origin} to {city}",
            "url": "https://utconline.uk.gov.in",
            "note": road_note + "Departure times and fares are not available here; check the "
                    "Uttarakhand Transport Corporation site or another trusted booking site."})

    seen = set()
    for d in plan["days"]:
        sid = d.get("stay")
        if sid and sid not in seen and sid in entities:
            seen.add(sid)
            ent = entities[sid]
            links["stays"].append({
                "label": ent["name"], "url": _maps_search(ent["name"], city),
                "note": "Open in Maps to check the location, contact details and current "
                        "prices before booking."})

    links["checklist"] = [
        "Book long-distance travel first (trains sell out earliest).",
        "Then book your stays; confirm room type and cancellation terms.",
        "Arrange local transport (taxi or shared) for transfers between towns.",
        "Check weather, road and permit advisories close to your travel date."]
    return links


def render_links(links: dict) -> str:
    out = ["## Booking checklist (you complete payment on the official sites)"]
    for step in links["checklist"]:
        out.append(f"- [ ] {step}")
    for title, key in (("Flights", "flights"), ("Trains", "trains"), ("Buses", "buses"),
                       ("Stays", "stays")):
        if links[key]:
            out += ["", f"**{title}**"]
            out += [f"- [{x['label']}]({x['url']}) - {x['note']}" for x in links[key]]
    return "\n".join(out)
