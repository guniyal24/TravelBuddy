import { useEffect, useState } from "react";
import { forgetAllMemories, forgetMemory, listMemories } from "../api.js";
import Icon from "./Icon.jsx";

// Long-term memory, fully visible and deletable. Preferences are learned only from trips you
// approved, and each one keeps the exact words it came from.
export default function Memories({ onExpired, active }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  const fail = (e) => (e.message === "SESSION_EXPIRED" ? onExpired() : setError(e.message));
  useEffect(() => {
    if (active) listMemories().then(setItems).catch(fail);
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  async function forget(key) {
    try { await forgetMemory(key); setItems((xs) => xs.filter((m) => m.key !== key)); } catch (e) { fail(e); }
  }
  async function forgetAll() {
    if (!window.confirm("Forget everything TravelBuddy remembers about you? This cannot be undone.")) return;
    try { await forgetAllMemories(); setItems([]); } catch (e) { fail(e); }
  }

  const prefs = (items || []).filter((m) => m.kind === "preference");
  const trips = (items || []).filter((m) => m.kind === "trip");
  return (
    <section className="card memories">
      <div className="page-head tight">
        <div>
          <h2><Icon name="spark" size={20} /> What I remember about you</h2>
          <p className="muted small">Learned only from trips you approved, and used to plan your next one. Delete anything at any time.</p>
        </div>
        {items?.length > 0 && <button type="button" className="link danger" onClick={forgetAll}>Forget everything</button>}
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {items === null && !error && <p className="muted">Loading…</p>}
      {items?.length === 0 && <p className="muted">Nothing yet. Approve a trip and I will remember what matters to you.</p>}
      {prefs.length > 0 && (
        <>
          <h3>Preferences</h3>
          <ul className="mem-list">
            {prefs.map((m) => (
              <li key={m.key}>
                <div><strong>{m.text}</strong>{m.quote && <q>{m.quote}</q>}</div>
                <button type="button" className="icon-btn" onClick={() => forget(m.key)} aria-label={`Forget: ${m.text}`}><Icon name="x" size={16} /></button>
              </li>
            ))}
          </ul>
        </>
      )}
      {trips.length > 0 && (
        <>
          <h3>Past trips</h3>
          <ul className="mem-list">
            {trips.map((m) => (
              <li key={m.key}>
                <div>{m.text}</div>
                <button type="button" className="icon-btn" onClick={() => forget(m.key)} aria-label="Forget this trip"><Icon name="x" size={16} /></button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
