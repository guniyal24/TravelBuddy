import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { MONTHS, TIERS } from "../data.js";
import Checklist from "./Checklist.jsx";
import Icon from "./Icon.jsx";
import MapView from "./MapView.jsx";
import Share from "./Share.jsx";
import Timeline from "./Timeline.jsx";

// Links open in a new tab; "Visit: / Eat: / Stay:" list lines get a small label.
const mdComponents = {
  a: ({ node, ...p }) => <a {...p} target="_blank" rel="noreferrer" />, // eslint-disable-line no-unused-vars
  li: ({ node, children }) => { // eslint-disable-line no-unused-vars
    const arr = Array.isArray(children) ? children : [children];
    const m = typeof arr[0] === "string" ? arr[0].match(/^(Visit|Eat|Stay):\s*([\s\S]*)$/) : null;
    if (!m) return <li>{children}</li>;
    return <li className={"item " + m[1].toLowerCase()}><span className="tag">{m[1]}</span>{m[2]}{arr.slice(1)}</li>;
  },
};
const Md = ({ children }) => (
  <div className="markdown"><ReactMarkdown components={mdComponents}>{children}</ReactMarkdown></div>
);

const money = (n) => "₹" + Math.round(n).toLocaleString("en-IN");

// Split the itinerary markdown into its "## " sections so each can be styled as a card.
function parse(md) {
  const parts = (md || "").split(/^## /m);
  const intro = parts.shift() || "";
  const sections = parts.map((p) => {
    const nl = p.indexOf("\n");
    return { head: (nl < 0 ? p : p.slice(0, nl)).trim(), body: nl < 0 ? "" : p.slice(nl + 1).trim() };
  });
  return { intro: intro.replace(/^# .*\n?/m, "").trim(), sections };
}

function Section({ head, body }) {
  if (head.includes("₹")) {
    const [, label, rest] = head.match(/^([^:₹]*):?\s*(.*)$/) || [null, "Estimated cost", head];
    return (
      <article className="costcard">
        <Icon name="wallet" size={22} />
        <div>
          <p className="cost-label">{label || "Estimated cost"}</p>
          <h3>{rest}</h3>
          {body && <Md>{body}</Md>}
        </div>
      </article>
    );
  }
  const day = head.match(/^\D*?(\d+)\s*[-–—:]?\s*(.*)$/);
  if (day && /^\D{0,12}\d/.test(head)) {
    return (
      <article className="daycard">
        <div className="daybadge"><small>Day</small>{day[1]}</div>
        <div className="daybody"><h3>{day[2] || head}</h3>{body && <Md>{body}</Md>}</div>
      </article>
    );
  }
  return <article className="sec"><h3>{head}</h3>{body && <Md>{body}</Md>}</article>;
}

function PlanText({ markdown }) {
  const { intro, sections } = parse(markdown);
  if (!sections.length) return <Md>{markdown || ""}</Md>;
  return (
    <div className="plantext">
      {intro && <Md>{intro}</Md>}
      {sections.map((s, i) => <Section key={i} {...s} />)}
    </div>
  );
}

function Banner({ trip }) {
  const r = trip.request || {};
  const total = trip.cost?.total_inr;
  const warn = (trip.warnings || []).length;
  return (
    <div className="tripbanner">
      <p className="eyebrow light">Your trip</p>
      <h2>{trip.title || "Your Uttarakhand trip"}</h2>
      <ul className="facts">
        {r.days && <li><Icon name="calendar" size={16} /> {r.days} {r.days === 1 ? "day" : "days"}</li>}
        {r.people && <li><Icon name="users" size={16} /> {r.people} {r.people === 1 ? "traveller" : "travellers"}</li>}
        {r.month >= 1 && r.month <= 12 && <li><Icon name="sun" size={16} /> {MONTHS[r.month - 1]}</li>}
        {r.tier && <li><Icon name="bed" size={16} /> {TIERS[r.tier] || r.tier}</li>}
        {warn > 0 && <li className="warnfact"><Icon name="alert" size={16} /> {warn} {warn === 1 ? "thing" : "things"} to check</li>}
      </ul>
      {total && (
        <div className="bigcost">
          <span>Estimated total</span>
          <strong>{money(total[0])} – {money(total[1])}</strong>
          {trip.cost?.per_person_inr && (
            <small>{money(trip.cost.per_person_inr[0])} – {money(trip.cost.per_person_inr[1])} per person</small>
          )}
        </div>
      )}
    </div>
  );
}

// markdown + timeline are always shown; checklist and share need a saved trip.
export default function TripView({ markdown, timeline, trip, onExpired }) {
  const [tab, setTab] = useState("plan");
  const tabs = [["plan", "Plan", "book"], ["timeline", "Timeline", "clock"], ["map", "Map", "map"],
    ...(trip ? [["checklist", "Checklist", "check"], ["share", "Share", "share"]] : [])];
  return (
    <div className="tripview">
      {trip && <Banner trip={trip} />}
      <div className="tvtabs" role="tablist">
        {tabs.map(([id, label, icon]) => (
          <button key={id} role="tab" aria-selected={tab === id}
                  className={tab === id ? "tvtab on" : "tvtab"} onClick={() => setTab(id)}>
            <Icon name={icon} size={17} /> {label}
          </button>
        ))}
      </div>
      <div className="tvpanel">
        {tab === "plan" && <PlanText markdown={markdown} />}
        {tab === "timeline" && <Timeline timeline={timeline} />}
        {tab === "map" && <MapView timeline={timeline} />}
        {tab === "checklist" && trip && <Checklist trip={trip} onExpired={onExpired} />}
        {tab === "share" && trip && <Share trip={trip} onExpired={onExpired} />}
      </div>
    </div>
  );
}
