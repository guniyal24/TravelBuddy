"""Plain-text summary for WhatsApp / messaging, and a PDF built from the same data.

The PDF uses a built-in Latin-1 font, so non-Latin characters (rupee sign, Hindi) are replaced:
the rupee sign becomes 'Rs.' and anything else unsupported becomes '?'. The PDF is therefore
always English; the on-screen itinerary and chat can be Hindi/Hinglish.
"""
from fpdf import FPDF


def _inr(n) -> str:
    return f"Rs.{int(n):,}"


def build_share_text(trip: dict) -> str:
    req, cost = trip["request"], trip["cost"]
    lo, hi = cost["total_inr"]
    out = [f"Uttarakhand trip: {req['days']} days, {req['people']} traveller(s)", ""]
    ents = trip["entities"]
    for day in trip["plan"]["days"]:
        names = [ents[i]["name"] for i in day.get("stops") or [] if i in ents]
        line = f"Day {day['day']} {day['destination'].removeprefix('destination_').title()}: "
        line += ", ".join(names) or "free day"
        if day.get("stay") and day["stay"] in ents:
            line += f" | Stay: {ents[day['stay']]['name']}"
        out.append(line.replace("_", " "))
    out += ["", f"Estimated cost: {_inr(lo)} to {_inr(hi)} total (estimate only).",
            "Planned with DevBhoomi Planner. Check weather, road and permit advisories "
            "before you travel."]
    return "\n".join(out)


def _latin(text: str) -> str:
    return text.replace("₹", "Rs.").encode("latin-1", "replace").decode("latin-1")


def build_pdf(trip: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(width, 9, _latin(trip.get("title", "Uttarakhand trip")),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for day in trip["timeline"]["days"]:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(width, 7, _latin(f"Day {day['day']} - {day['label']}"),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for it in day["items"]:
            line = f"{it['time']}  {it['title']}" + (f"  ({it['note']})" if it.get("note") else "")
            pdf.multi_cell(width, 5.5, _latin(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    lo, hi = trip["cost"]["total_inr"]
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(width, 7, _latin(f"Estimated cost: {_inr(lo)} - {_inr(hi)} total"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for item in trip["cost"]["items"]:
        tag = "" if item["source"] == "listing" else f" ({item['source']})"
        pdf.multi_cell(width, 5.5, _latin(
            f"- {item['label']}: {_inr(item['low'])} - {_inr(item['high'])}{tag}"),
            new_x="LMARGIN", new_y="NEXT")
    if trip.get("warnings"):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(width, 7, "Things to check", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for w in trip["warnings"]:
            pdf.multi_cell(width, 5.5, _latin(f"- {w}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(width, 5, "Estimate only. Distances are straight-line. Check weather, road "
                   "and permit advisories before you travel.", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
