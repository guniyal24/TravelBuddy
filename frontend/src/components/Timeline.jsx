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
            <h3>{d.label}</h3>
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
