import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const COLORS = ["#043e56", "#e94d04", "#1b81b5", "#7b3fa0", "#0b8a6f", "#c28a00", "#b3264e"];
const gmaps = (p) => `https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lon}`;

export default function MapView({ timeline }) {
  const el = useRef(null);
  const [day, setDay] = useState(0); // 0 = all days
  const all = timeline?.points || [];
  const points = day ? all.filter((p) => p.day === day) : all;
  const days = [...new Set(all.map((p) => p.day))];

  useEffect(() => {
    if (!el.current || !points.length) return undefined;
    const map = L.map(el.current, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
    const byDay = {};
    points.forEach((p) => { (byDay[p.day] ||= []).push(p); });
    Object.entries(byDay).forEach(([d, pts]) => {
      const color = COLORS[(Number(d) - 1) % COLORS.length];
      L.polyline(pts.map((p) => [p.lat, p.lon]), { color, weight: 3, opacity: 0.7, dashArray: "6 6" }).addTo(map);
      pts.forEach((p, i) => {
        L.marker([p.lat, p.lon], { icon: L.divIcon({
          className: "pin", html: `<span style="background:${color}">${i + 1}</span>`, iconSize: [26, 26] }) })
          .bindPopup(`<strong>Day ${p.day}, ${p.time}</strong><br>${p.title.replace(/</g, "&lt;")}`).addTo(map);
      });
    });
    map.fitBounds(points.map((p) => [p.lat, p.lon]), { padding: [30, 30], maxZoom: 14 });
    return () => map.remove();
  }, [points.length, day, timeline]);

  if (!all.length) return <p className="muted">No mapped places in this plan (some listings have no coordinates).</p>;
  return (
    <div>
      <div className="chips" role="group" aria-label="Show day">
        <button className={day === 0 ? "chip on" : "chip"} onClick={() => setDay(0)}>All days</button>
        {days.map((d) => (
          <button key={d} className={day === d ? "chip on" : "chip"} onClick={() => setDay(d)}>Day {d}</button>
        ))}
      </div>
      <div ref={el} className="map" role="img" aria-label="Map of your planned stops" />
      <p className="muted small">
        Straight lines are not roads. The map needs an internet connection; offline, use the list below.
      </p>
      <ul className="plain">
        {points.map((p, i) => (
          <li key={i} className="ck">Day {p.day}, {p.time}: <a href={gmaps(p)} target="_blank" rel="noreferrer">{p.title}</a></li>
        ))}
      </ul>
    </div>
  );
}
