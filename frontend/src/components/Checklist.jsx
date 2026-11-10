import { useState } from "react";
import { setCheck } from "../api.js";

const GROUPS = [["flights", "Flights"], ["trains", "Trains"], ["buses", "Buses"],
  ["stays", "Stays"], ["todo", "Before you go"]];

export default function Checklist({ trip, onExpired }) {
  const [items, setItems] = useState(trip.checklist || []);
  const [error, setError] = useState("");
  const done = items.filter((i) => i.done).length;
  const pct = items.length ? Math.round((done / items.length) * 100) : 0;

  async function toggle(item) {
    const next = !item.done;
    setItems((cur) => cur.map((i) => (i.id === item.id ? { ...i, done: next } : i)));
    try { await setCheck(trip.trip_id, item.id, next); setError(""); }
    catch (e) {
      setItems((cur) => cur.map((i) => (i.id === item.id ? { ...i, done: !next } : i)));
      if (e.message === "SESSION_EXPIRED") return onExpired();
      setError("Could not save that tick. Check your connection and try again.");
    }
  }

  return (
    <div className="checklist">
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
           aria-label="Checklist progress">
        <div className="progress-bar" style={{ width: pct + "%" }} />
      </div>
      <p className="muted">
        {done} of {items.length} done. You pay on the official sites; ticking here only tracks your progress.
      </p>
      {error && <div className="error" role="alert">{error}</div>}
      {GROUPS.map(([kind, title]) => {
        const rows = items.filter((i) => i.kind === kind);
        return rows.length > 0 && (
          <section key={kind} className="ck-group">
            <h3>{title}</h3>
            <ul className="plain">
              {rows.map((i) => (
                <li key={i.id} className={i.done ? "ck done" : "ck"}>
                  <label className="check">
                    <input type="checkbox" checked={!!i.done} onChange={() => toggle(i)} />
                    <span>
                      {i.url ? <a href={i.url} target="_blank" rel="noreferrer">{i.label}</a> : i.label}
                      {i.note && <span className="muted small"> {i.note}</span>}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
