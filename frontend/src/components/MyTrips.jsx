import { useEffect, useState } from "react";
import { cachedTrips, getTrip, listTrips } from "../api.js";
import Icon from "./Icon.jsx";

const GRADS = [["#043e56", "#2f87b5"], ["#c2410c", "#f59a3c"], ["#0f766e", "#3dbfae"],
  ["#1d4f91", "#5d9be0"], ["#7a3412", "#e9782a"], ["#0b5563", "#35a9b8"]];

export default function MyTrips({ onOpen, onExpired, onPlan, active }) {
  const [trips, setTrips] = useState(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!active) return;
    setError("");
    listTrips().then((t) => { setTrips(t); setOffline(false); }).catch((e) => {
      if (e.message === "SESSION_EXPIRED") return onExpired();
      setOffline(true);
      setTrips(cachedTrips().map((t) => ({ trip_id: t.trip_id, title: t.title, updated_at: t.created_at })));
    });
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  async function open(t) {
    setError("");
    try { onOpen(await getTrip(t.trip_id)); }
    catch (e) {
      if (e.message === "SESSION_EXPIRED") return onExpired();
      const local = cachedTrips().find((c) => c.trip_id === t.trip_id);
      local ? onOpen(local) : setError(e.message);
    }
  }

  if (trips === null) return <div className="card center"><div className="spinner" /></div>;
  return (
    <section>
      <div className="page-head">
        <h1>My trips</h1>
        <button className="primary" onClick={onPlan}><Icon name="plus" size={18} /> New trip</button>
      </div>
      {offline && <div className="notice" role="status"><Icon name="wifioff" size={16} /> Offline: showing trips saved on this device.</div>}
      {error && <div className="error" role="alert">{error}</div>}
      {trips.length === 0 && (
        <div className="empty">
          <Icon name="trips" size={40} />
          <h2>No trips yet</h2>
          <p className="muted">Plan a trip and approve it. It will be saved here, with its checklist.</p>
          <button className="primary lg" onClick={onPlan}>Plan my first trip <Icon name="arrow" size={18} /></button>
        </div>
      )}
      <ul className="trip-grid">
        {trips.map((t, i) => {
          const g = GRADS[i % GRADS.length];
          return (
            <li key={t.trip_id}>
              <button className="trip-card" onClick={() => open(t)} style={{ "--g1": g[0], "--g2": g[1] }}>
                <span className="trip-thumb"><Icon name="map" size={26} /></span>
                <span className="trip-meta">
                  <strong>{t.title}</strong>
                  <span className="muted small"><Icon name="calendar" size={13} /> {new Date(t.updated_at).toLocaleDateString()}</span>
                </span>
                <Icon name="chevron" size={18} />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
