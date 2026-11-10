import { useEffect, useState } from "react";
import { cacheTrip, replanTrip, resumeTrip, startTrip } from "../api.js";
import { DESTINATIONS, MONTHS } from "../data.js";
import AgentTrace, { mergeEvents } from "./AgentTrace.jsx";
import { HotelPicker } from "./Hotels.jsx";
import Icon from "./Icon.jsx";
import Mountains from "./Mountains.jsx";
import TripView from "./TripView.jsx";

const STEPS = ["Describe", "Choose", "Review", "Hotels", "Book"];
const STEP_OF = { ask: 0, choose: 1, approve: 2, hotels: 3, done: 4 };

const EXAMPLES = [
  ["Temples and food, 3 days", "I want a 3 day trip in November for 2 people from Pune, budget stay, love temples and local food"],
  ["Family weekend in Nainital", "A relaxed long weekend in Nainital for a family of 4, mid-range hotels"],
  ["Hinglish: Kumaon trip", "Nainital aur Almora, 4 din, vegetarian khana, 2 log, December"],
];
const EXAMPLE = EXAMPLES[0][1];

const WHAT_YOU_GET = [
  ["calendar", "Day-by-day plan", "Stops, meals and stays for each day."],
  ["wallet", "Cost range", "Labelled as listing or assumption."],
  ["shield", "Safety notes", "Altitude, health and permits."],
  ["map", "Map and timeline", "See your route and daily rhythm."],
];

export default function Trip({ onExpired, initialTrip }) {
  const [text, setText] = useState("");
  const [tripId, setTripId] = useState(null);
  const [prompt, setPrompt] = useState(null);
  const [itinerary, setItinerary] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | busy | waiting | done | cancelled
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState("");
  const [change, setChange] = useState("");
  const [trip, setTrip] = useState(null); // the saved trip once approved
  const [fromDay, setFromDay] = useState(1);
  const [reason, setReason] = useState("");
  const [trace, setTrace] = useState([]); // every agent step of this planning session
  const [since, setSince] = useState(0);

  useEffect(() => {
    if (!initialTrip) return;
    cacheTrip(initialTrip);
    setTrip(initialTrip); setTripId(initialTrip.trip_id); setItinerary(initialTrip.itinerary);
    setPrompt(null); setStatus("done"); setError(""); setTrace([]);
  }, [initialTrip]);

  const step = status === "done" ? 4 : prompt ? (STEP_OF[prompt.type] ?? 0) : 0;

  // fn receives onEvent: the server streams each agent step while it works
  async function run(fn, { fresh = false } = {}) {
    setError(""); setStatus("busy"); setSince(Date.now());
    if (fresh) setTrace([]);
    const onEvent = (ev) => setTrace((t) => mergeEvents(t, ev));
    try {
      const r = await fn(onEvent);
      setTripId(r.trip_id);
      if (r.status === "waiting") { setPrompt(r.prompt); setStatus("waiting"); }
      else {
        setPrompt(null); setItinerary(r.itinerary); setStatus(r.status);
        setTrip(r.trip || null);
        if (r.trip) cacheTrip(r.trip);
      }
    } catch (e) {
      if (e.message === "SESSION_EXPIRED") return onExpired();
      setError(e.message); setStatus(prompt ? "waiting" : "idle");
    }
  }

  const start = (e) => { e.preventDefault(); if (text.trim()) run((on) => startTrip(text.trim(), on), { fresh: true }); };
  const reply = (value) => { setAnswer(""); setChange(""); return run((on) => resumeTrip(tripId, value, on)); };
  const reset = () => {
    setText(""); setTripId(null); setPrompt(null); setItinerary(null); setTrip(null);
    setReason(""); setFromDay(1); setStatus("idle"); setError(""); setTrace([]);
  };
  const agents = new Set(trace.map((s) => s.agent).filter((a) => a !== "You")).size;
  const how = trace.length > 0 && (
    <details className="trace-wrap">
      <summary><Icon name="spark" size={16} /> See how {agents} AI and rule-based agents built this</summary>
      <AgentTrace steps={trace} title="Agent trace" />
    </details>
  );
  const pick = (name) => setText(`3 day trip to ${name} for 2 people in ${MONTHS[new Date().getMonth()]}, mid-range stay`);

  return (
    <section className="plan">
      {status !== "idle" && (
        <ol className="stepper" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s} className={i === step ? "now" : i < step ? "past" : ""} aria-current={i === step ? "step" : undefined}>
              <span className="dot">{i < step ? <Icon name="check" size={14} /> : i + 1}</span>
              <span className="lbl">{s}</span>
            </li>
          ))}
        </ol>
      )}

      {error && <div className="error" role="alert"><Icon name="alert" size={18} /> {error}</div>}

      {status === "idle" && (
        <>
          <form className="plan-hero" onSubmit={start}>
            <Mountains className="plan-hero-art" />
            <p className="eyebrow light">AI trip planner</p>
            <h1>Where to next?</h1>
            <p className="plan-sub">
              Describe your trip in your own words: days, people, month, budget and what you enjoy.
              English, Hindi and Hinglish all work.
            </p>
            <div className="prompt-box">
              <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)}
                        placeholder={EXAMPLE} aria-label="Describe your trip" />
              <div className="prompt-foot">
                <div className="chips tight" aria-label="Examples">
                  {EXAMPLES.map(([label, t]) => (
                    <button key={label} type="button" className="chip" onClick={() => setText(t)}>{label}</button>
                  ))}
                </div>
                <button className="primary lg" disabled={!text.trim()}>
                  Plan my trip <Icon name="arrow" size={18} />
                </button>
              </div>
            </div>
          </form>

          <h2 className="h-sm">Popular towns</h2>
          <div className="picks">
            {DESTINATIONS.map((d) => (
              <button key={d.id} className="pick" onClick={() => { pick(d.name); window.scrollTo({ top: 0, behavior: "smooth" }); }}
                      style={{ "--g1": d.g[0], "--g2": d.g[1] }}>
                <span className="pick-dot" />
                <span><strong>{d.name}</strong><small>{d.tags.join(" · ")}</small></span>
              </button>
            ))}
          </div>

          <h2 className="h-sm">What you get</h2>
          <div className="get-grid">
            {WHAT_YOU_GET.map(([icon, title, sub]) => (
              <div key={title} className="get">
                <span className="icon-chip"><Icon name={icon} size={20} /></span>
                <strong>{title}</strong><span className="muted">{sub}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {status === "busy" && (
        <div className="card busy" role="status">
          <h2>Planning your trip</h2>
          <p className="muted small">
            Live from the server: specialist agents research, draft, check and price your plan.
            An LLM writes the draft; rule-based agents check it. This usually takes under a minute.
          </p>
          <AgentTrace steps={trace} live since={since} />
        </div>
      )}

      {status === "waiting" && prompt?.type === "ask" && (
        <form className="card" onSubmit={(e) => { e.preventDefault(); answer.trim() && reply(answer.trim()); }}>
          <span className="icon-chip"><Icon name="chat" size={20} /></span>
          <h2>One more thing</h2>
          <p>{prompt.message}</p>
          <input value={answer} onChange={(e) => setAnswer(e.target.value)} autoFocus
                 placeholder="e.g. 2 people in November" aria-label="Your answer" />
          <button className="primary lg" disabled={!answer.trim()}>Continue <Icon name="arrow" size={18} /></button>
        </form>
      )}

      {status === "waiting" && prompt?.type === "choose" && (
        <div className="card">
          <h2>{prompt.message}</h2>
          {how}
          <div className="options">
            {prompt.options.map((o) => (
              <button key={o.id} className="option" onClick={() => reply(o.id)}>
                <span className="option-icon"><Icon name="route" size={20} /></span>
                <span className="option-body">
                  <strong>{o.label}</strong>
                  {o.visited?.length > 0 && <span className="pill"><Icon name="clock" size={13} /> You visited {o.visited.join(" and ")} before</span>}
                  {o.reasons.length > 0
                    ? <span className="pill warn"><Icon name="alert" size={13} /> Heads-up: {o.reasons.join("; ")}</span>
                    : <span className="pill ok"><Icon name="check" size={13} /> Good fit for your dates</span>}
                </span>
                <Icon name="chevron" size={18} />
              </button>
            ))}
          </div>
        </div>
      )}

      {status === "waiting" && prompt?.type === "approve" && (
        <div className="card flush">
          <div className="card-pad"><h2>Review your plan</h2>{how}</div>
          <TripView markdown={prompt.preview} timeline={prompt.timeline} />
          <div className="actionbar">
            <div className="actions">
              <button className="primary lg" onClick={() => reply({ action: "approve" })}>
                <Icon name="check" size={18} /> Approve plan
              </button>
              <button className="link danger" onClick={() => reply({ action: "cancel" })}>Cancel</button>
            </div>
            <form className="change" onSubmit={(e) => { e.preventDefault(); change.trim() && reply({ action: "edit", text: change.trim() }); }}>
              <input value={change} onChange={(e) => setChange(e.target.value)}
                     placeholder="Or ask for a change, e.g. less walking, add a yoga class"
                     aria-label="Requested change" />
              <button disabled={!change.trim()}>Update plan</button>
            </form>
          </div>
        </div>
      )}

      {status === "waiting" && prompt?.type === "hotels" && (
        <>
          {how && <div className="card-pad">{how}</div>}
          <HotelPicker prompt={prompt} onSubmit={(v) => reply(v)} />
        </>
      )}

      {status === "done" && (
        <div className="card flush">
          {trace.length > 0 && <div className="card-pad">{how}</div>}
          <TripView markdown={itinerary} timeline={trip?.timeline} trip={trip} onExpired={onExpired} />
          {trip && (
            <form className="replan" onSubmit={(e) => {
              e.preventDefault();
              if (reason.trim()) { const r = reason.trim(); setReason(""); run((on) => replanTrip(tripId, Number(fromDay), r, on), { fresh: true }); }
            }}>
              <h3><Icon name="refresh" size={18} /> Plans changed?</h3>
              <div className="replan-row">
                <label>Re-plan from
                  <select value={fromDay} onChange={(e) => setFromDay(e.target.value)}>
                    {Array.from({ length: trip.request.days }, (_, i) => i + 1).map((d) => (
                      <option key={d} value={d}>Day {d}</option>
                    ))}
                  </select>
                </label>
                <input value={reason} onChange={(e) => setReason(e.target.value)}
                       placeholder="e.g. heavy rain forecast, bus cancelled, want fewer temples"
                       aria-label="What changed" />
                <button className="primary" disabled={!reason.trim()}>Re-plan</button>
              </div>
              <p className="muted small">Days before the one you pick stay exactly as they are.</p>
            </form>
          )}
          <div className="actionbar">
            <div className="actions">
              <button onClick={() => window.print()}><Icon name="print" size={18} /> Print</button>
              <button onClick={reset}><Icon name="plus" size={18} /> Plan another trip</button>
            </div>
          </div>
        </div>
      )}

      {status === "cancelled" && (
        <div className="card center">
          <p>Plan cancelled.</p>
          <button className="primary" onClick={reset}>Start again</button>
        </div>
      )}
    </section>
  );
}
