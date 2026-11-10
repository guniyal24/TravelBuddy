"""Calendar (.ics) export of the timeline. Times are Asia/Kolkata (no daylight saving)."""
from datetime import UTC, date, datetime, timedelta

TZ = ("BEGIN:VTIMEZONE\r\nTZID:Asia/Kolkata\r\nBEGIN:STANDARD\r\n"
      "DTSTART:19700101T000000\r\nTZOFFSETFROM:+0530\r\nTZOFFSETTO:+0530\r\nTZNAME:IST\r\n"
      "END:STANDARD\r\nEND:VTIMEZONE\r\n")


def _esc(text: str) -> str:
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return text.replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 line folding at 75 octets, never splitting a UTF-8 character."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > (75 if not out else 74):
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n ".join(out)


def _stamp(d: date, hhmm: str) -> str:
    return f"{d.strftime('%Y%m%d')}T{hhmm.replace(':', '')}00"


def build_ics(trip: dict, start: date, now: datetime | None = None) -> str:
    trip_id = trip.get("trip_id", "trip")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DevBhoomi Planner//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    out = "\r\n".join(lines) + "\r\n" + TZ
    for day in trip["timeline"]["days"]:
        d = start + timedelta(days=day["day"] - 1)
        for i, it in enumerate(day["items"]):
            ev = ["BEGIN:VEVENT", f"UID:{trip_id}-{day['day']}-{i}@devbhoomi-planner",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;TZID=Asia/Kolkata:{_stamp(d, it['time'])}",
                  f"DTEND;TZID=Asia/Kolkata:{_stamp(d, it['end'])}",
                  f"SUMMARY:{_esc(it['title'])}",
                  "DESCRIPTION:" + _esc(f"{it.get('note') or ''} Suggested time; check "
                                       "opening hours.".strip())]
            if it.get("lat") is not None and it.get("lon") is not None:
                ev.append(f"GEO:{it['lat']};{it['lon']}")
            ev.append("END:VEVENT")
            out += "\r\n".join(_fold(x) for x in ev) + "\r\n"
    return out + "END:VCALENDAR\r\n"
