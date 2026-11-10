import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";

// Live view of the planner's agents, built from the server's progress events. Each graph step
// sends "start" and then "end" (or "wait" when it pauses for you) with the same id.
export function mergeEvents(list, ev) {
  const i = list.findIndex((s) => s.id === ev.id && s.phase === "start");
  if (i < 0) return [...list, ev];
  const next = list.slice();
  next[i] = { ...list[i], ...ev };
  return next;
}

const fmt = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

function Elapsed({ since }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);
  return <span className="trace-clock">{((now - since) / 1000).toFixed(1)} s</span>;
}

export default function AgentTrace({ steps, live = false, since, title = "Agents at work", usage }) {
  if (!steps.length && !live) return null;
  const total = steps.reduce((n, s) => n + (s.ms || 0), 0);
  return (
    <section className="trace" aria-label={title} aria-live={live ? "polite" : undefined}>
      <header className="trace-head">
        <strong>{live && <span className="live-dot" aria-hidden="true" />}{title}</strong>
        {live && since ? <Elapsed since={since} /> : total > 0 && <span className="trace-clock">{steps.length} steps · {fmt(total)}</span>}
      </header>
      <ol className="trace-list">
        {steps.map((s) => {
          const running = s.phase === "start";
          const icon = s.phase === "wait" ? "clock" : s.tone === "warn" ? "alert" : "check";
          return (
            <li key={s.id + s.phase} className={`trace-step ${running ? "running" : s.tone || "info"}`}>
              <span className="trace-icon">{running ? <span className="mini-spin" /> : <Icon name={icon} size={14} />}</span>
              <div className="trace-body">
                <div className="trace-line">
                  <span className={`agent-badge a-${s.node}`}>{s.agent}</span>
                  <span className="trace-msg">{s.message}</span>
                  {!running && s.ms > 0 && s.phase !== "wait" && <span className="trace-ms">{fmt(s.ms)}</span>}
                </div>
                {s.details?.length > 0 && (
                  <ul className="trace-details">{s.details.map((d, i) => <li key={i}>{d}</li>)}</ul>
                )}
              </div>
            </li>
          );
        })}
        {live && !steps.some((s) => s.phase === "start") && (
          <li className="trace-step running"><span className="trace-icon"><span className="mini-spin" /></span>
            <div className="trace-body"><span className="trace-msg muted">{steps.length ? "Handing over to the next agent…" : "Connecting to the planner…"}</span></div></li>
        )}
      </ol>
      {usage?.llm_calls > 0 && (
        <p className="trace-usage">
          {usage.llm_calls} LLM calls · {(usage.tokens_in + usage.tokens_out).toLocaleString()} tokens ·
          about ₹{(usage.cost_usd * 88).toFixed(2)} (${usage.cost_usd.toFixed(4)}) · {usage.seconds.toFixed(1)} s of agent time
        </p>
      )}
    </section>
  );
}
