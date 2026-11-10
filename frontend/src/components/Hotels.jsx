import { useState } from "react";
import Icon from "./Icon.jsx";

// Concierge results: researched hotels per overnight town (ranked in code on the server) and
// verified travel notes. Every pro/con quotes a real review, shown with its author (Google's
// attribution rules); every travel note links its source.

const ASPECT_LABEL = { cleanliness: "Cleanliness", location: "Location", value: "Value", staff: "Staff", comfort: "Comfort" };

function Stars({ rating, count }) {
  if (rating == null) return <span className="muted small">No Google rating found</span>;
  return <span className="stars"><Icon name="spark" size={14} /> {rating.toFixed(1)} <span className="muted">({count.toLocaleString()} reviews)</span></span>;
}

function Quote({ claim, reviews, tone }) {
  const r = reviews.find((x) => x.id === claim.review_id);
  return (
    <li className={`quote ${tone}`}>
      <strong>{claim.point}</strong>
      <q>{claim.quote}</q>
      {r && <cite>{r.author_uri ? <a href={r.author_uri} target="_blank" rel="noreferrer">{r.author}</a> : r.author}, Google review{r.when ? `, ${r.when}` : ""}</cite>}
    </li>
  );
}

function HotelCard({ o, rank, selected, current, onPick, readOnly }) {
  const a = o.analysis || {};
  const aspects = Object.entries(a.aspects || {});
  return (
    <div className={`hotel ${selected ? "sel" : ""}`} onClick={readOnly ? undefined : onPick}
         role={readOnly ? undefined : "radio"} aria-checked={readOnly ? undefined : selected}
         tabIndex={readOnly ? undefined : 0}
         onKeyDown={(e) => !readOnly && (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onPick())}>
      <div className="hotel-head">
        <div>
          <div className="hotel-tags">
            {rank === 0 && <span className="pill ok">Top pick</span>}
            {current && <span className="pill">In your plan</span>}
            {o.tier && <span className="pill">{o.tier}</span>}
          </div>
          <h4>{o.name}</h4>
          <Stars rating={o.google?.rating} count={o.google?.review_count || 0} />
        </div>
        {!readOnly && <span className={`radio ${selected ? "on" : ""}`} aria-hidden="true" />}
      </div>
      {o.price_text && <p className="muted small">Listed price: {o.price_text}</p>}
      {a.summary && <p>{a.summary}</p>}
      {aspects.length > 0 && (
        <div className="aspects">
          {aspects.map(([k, v]) => (
            <div key={k} className="aspect"><span>{ASPECT_LABEL[k] || k}</span>
              <span className="bar"><i style={{ width: `${(v / 5) * 100}%` }} /></span><b>{v}</b></div>
          ))}
        </div>
      )}
      {(a.pros?.length > 0 || a.cons?.length > 0) && (
        <ul className="quotes">
          {(a.pros || []).map((c, i) => <Quote key={`p${i}`} claim={c} reviews={o.reviews || []} tone="pro" />)}
          {(a.cons || []).map((c, i) => <Quote key={`c${i}`} claim={c} reviews={o.reviews || []} tone="con" />)}
        </ul>
      )}
      <p className="why"><Icon name="check" size={14} /> {(o.reasons || []).join(" · ")}</p>
      {o.google?.maps_url && <a className="small" href={o.google.maps_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>Open in Google Maps</a>}
    </div>
  );
}

function TravelNotes({ travel }) {
  if (!travel) return null;
  if (!travel.available) {
    return <p className="muted small"><Icon name="alert" size={14} /> Live travel notes are off ({travel.reason || "web search not configured"}). Check road and weather advisories before you go.</p>;
  }
  if (!travel.notes?.length) return <p className="muted small">No current travel notes found for your towns.</p>;
  return (
    <ul className="travel-notes">
      {travel.notes.map((n, i) => (
        <li key={i}><strong>{n.town}:</strong> {n.text} <a href={n.url} target="_blank" rel="noreferrer">{new URL(n.url).hostname}</a></li>
      ))}
    </ul>
  );
}

function Verified({ towns }) {
  const claims = towns.reduce((s, t) => s + (t.claims || 0), 0);
  const kept = towns.reduce((s, t) => s + (t.verified || 0), 0);
  if (!claims) return null;
  return <p className="muted small"><Icon name="shield" size={14} /> {kept} of {claims} review claims passed the quote check; the rest were dropped.</p>;
}

export function HotelPicker({ prompt, onSubmit }) {
  const [picks, setPicks] = useState(() => Object.fromEntries(prompt.towns.map((t) => [t.dest, t.current || t.options[0]?.stay_id])));
  return (
    <div className="card">
      <span className="icon-chip"><Icon name="bed" size={20} /></span>
      <h2>Choose your hotels</h2>
      <p>{prompt.message}</p>
      <Verified towns={prompt.towns} />
      {prompt.towns.map((t) => (
        <section key={t.dest} className="town" role="radiogroup" aria-label={`Hotels in ${t.town}`}>
          <h3>{t.town} <span className="muted small">· {t.nights} night{t.nights === 1 ? "" : "s"}</span></h3>
          <div className="hotels">
            {t.options.map((o, i) => (
              <HotelCard key={o.stay_id} o={o} rank={i} current={o.stay_id === t.current}
                         selected={picks[t.dest] === o.stay_id}
                         onPick={() => setPicks((p) => ({ ...p, [t.dest]: o.stay_id }))} />
            ))}
          </div>
        </section>
      ))}
      <h3>Travel notes</h3>
      <TravelNotes travel={prompt.travel} />
      <p className="muted small">Ratings and reviews from Google. Ranking is computed from rating, review count, tier and budget, not by the AI.</p>
      <div className="actions">
        <button className="primary lg" onClick={() => onSubmit({ choices: picks })}><Icon name="check" size={18} /> Confirm hotels</button>
        <button className="link" onClick={() => onSubmit({ choices: {} })}>Keep the hotels in my plan</button>
      </div>
    </div>
  );
}

export function HotelSummary({ concierge }) {
  if (!concierge?.towns?.length) return <p className="muted">No hotel research for this trip.</p>;
  return (
    <div className="hotel-summary">
      <Verified towns={concierge.towns} />
      {concierge.towns.map((t) => {
        const chosen = t.options.find((o) => o.stay_id === t.chosen) || t.options[0];
        return (
          <section key={t.dest} className="town">
            <h3>{t.town}</h3>
            {chosen && <HotelCard o={chosen} rank={-1} current readOnly />}
          </section>
        );
      })}
      <h3>Travel notes</h3>
      <TravelNotes travel={concierge.travel} />
      <p className="muted small">Ratings and reviews from Google.</p>
    </div>
  );
}
