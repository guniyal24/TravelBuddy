import { useState } from "react";
import { exportTrip } from "../api.js";
import Icon from "./Icon.jsx";

function save(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Share({ trip, onExpired }) {
  const [start, setStart] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function go(kind) {
    setMsg(""); setBusy(true);
    try {
      if (kind === "ics" && !start) { setMsg("Pick your first travel day for the calendar file."); return; }
      const res = await exportTrip(trip.trip_id, kind === "wa" || kind === "copy" ? "txt" : kind, start);
      if (kind === "wa") {
        window.open("https://wa.me/?text=" + encodeURIComponent(await res.text()), "_blank", "noopener");
      } else if (kind === "copy") {
        try { await navigator.clipboard.writeText(await res.text()); setMsg("Copied."); }
        catch { setMsg("Could not copy. Use the WhatsApp or PDF option instead."); }
      } else {
        save(await res.blob(), `travelbuddy-trip.${kind}`);
      }
    } catch (e) {
      if (e.message === "SESSION_EXPIRED") return onExpired();
      setMsg(e.message);
    } finally { setBusy(false); }
  }

  return (
    <div className="share">
      <p className="muted">
        Share a short summary, or download the plan. The PDF and WhatsApp summary are in English.
      </p>
      <div className="share-grid">
        <button className="share-card wa" disabled={busy} onClick={() => go("wa")}>
          <Icon name="share" size={22} /><strong>WhatsApp</strong><span>Send a short summary</span>
        </button>
        <button className="share-card" disabled={busy} onClick={() => go("copy")}>
          <Icon name="copy" size={22} /><strong>Copy summary</strong><span>Paste it anywhere</span>
        </button>
        <button className="share-card" disabled={busy} onClick={() => go("pdf")}>
          <Icon name="download" size={22} /><strong>Download PDF</strong><span>Print or keep offline</span>
        </button>
      </div>
      <div className="ics">
        <label>First travel day
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <button disabled={busy} onClick={() => go("ics")}><Icon name="calendar" size={18} /> Add to calendar (.ics)</button>
      </div>
      {msg && <div className="notice" role="status">{msg}</div>}
    </div>
  );
}
