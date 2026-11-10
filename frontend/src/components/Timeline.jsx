import Icon from "./Icon.jsx";

const LABEL = { stop: "Visit", meal: "Eat", stay: "Stay", transfer: "Travel" };
const ICON = { stop: "pin", meal: "food", stay: "bed", transfer: "bus" };

export default function Timeline({ timeline }) {
  if (!timeline?.days?.length) return <p className="muted">No timeline available.</p>;
  return (
    <div className="timeline">
      {timeline.days.map((d) => (
        <section key={d.day} className="tl-day">
          <header>
            <span className="daybadge"><small>Day</small>{d.day}</span>
            <div>
              <h3>{d.label}</h3>
              {d.date && <span className="muted small">{new Date(d.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</span>}
            </div>
            {d.weather?.max_c != null && (
              <span className={`wx ${d.weather.kind === "forecast" && d.weather.rain_mm >= 30 ? "wet" : ""}`}
                    title={d.weather.kind === "forecast" ? "Forecast (Open-Meteo)" : "Typical for these dates, not a forecast"}>
                <Icon name="sun" size={14} /> {Math.round(d.weather.min_c)}–{Math.round(d.weather.max_c)}°C · {Math.round(d.weather.rain_mm || 0)} mm
                {d.weather.kind !== "forecast" && <em> typical</em>}
              </span>
            )}
          </header>
          <ol>
            {d.items.map((it, i) => (
              <li key={i} className={"tl " + it.kind}>
                <time>{it.time}</time>
                <span className="tl-ico"><Icon name={ICON[it.kind] || "pin"} size={15} /></span>
                <div>
                  <span className="tag">{LABEL[it.kind] || it.kind}</span> {it.title}
                  {it.note && <div className="muted small">{it.note}</div>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}
      <p className="muted small">{timeline.note}</p>
    </div>
  );
}
