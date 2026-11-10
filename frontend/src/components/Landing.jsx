import { DESTINATIONS, FAQ, FEATURES, STACK, STEPS_INFO } from "../data.js";
import Icon from "./Icon.jsx";
import Logo from "./Logo.jsx";
import Mountains from "./Mountains.jsx";

const SAMPLE = [
  { kind: "stop", time: "07:00", label: "Visit", text: "Har Ki Pauri, morning on the ghats" },
  { kind: "meal", time: "12:30", label: "Eat", text: "A local thali near the market" },
  { kind: "stop", time: "17:30", label: "Visit", text: "Evening Ganga aarti" },
  { kind: "stay", time: "20:30", label: "Stay", text: "A budget stay close to the ghats" },
];

const STATS = [
  ["9", "towns you can plan"],
  ["300+", "places and stays in the data"],
  ["3", "languages: English, Hindi, Hinglish"],
  ["You", "approve every plan before it is saved"],
];

export default function Landing({ onLogin, onRegister, onGuest, guestBusy }) {
  return (
    <div className="landing">
      <section className="hero">
        <div className="hero-glow" /><div className="sun" />
        <header className="lnav container">
          <Logo height={42} />
          <nav className="lnav-links" aria-label="Sections">
            <a href="#how">How it works</a>
            <a href="#destinations">Destinations</a>
            <a href="#features">Features</a>
            <a href="#faq">FAQ</a>
          </nav>
          <div className="lnav-cta">
            <button className="btn-ghost" onClick={onLogin}>Log in</button>
            <button className="btn-navy" onClick={onRegister}>Get started</button>
          </div>
        </header>

        <div className="container hero-grid">
          <div className="hero-copy">
            <span className="pill-hero"><Icon name="spark" size={14} /> AI trip planner for Uttarakhand</span>
            <h1>Plan your Himalayan trip like a <em>local</em>.</h1>
            <p className="lead">
              Tell TravelBuddy where, when and how you like to travel. It researches real places,
              checks the season and safety, and hands you a day-by-day plan with a cost range and a booking checklist.
            </p>
            <div className="hero-actions">
              <button className="btn-accent lg" onClick={onGuest} disabled={guestBusy}>
                {guestBusy ? "Opening…" : <>Try it now, no sign-up <Icon name="arrow" size={18} /></>}
              </button>
              <a className="btn-outline lg" href="#how">See how it works</a>
            </div>
            <p className="hero-note">Free guest session. Watch the AI agents plan your trip live.</p>
            <ul className="trust">
              <li><Icon name="book" size={16} /> Uses real listings</li>
              <li><Icon name="shield" size={16} /> Safety-checked</li>
              <li><Icon name="language" size={16} /> Hindi and Hinglish</li>
            </ul>
          </div>

          <aside className="sample" aria-label="Example itinerary">
            <div className="sample-head">
              <span className="daybadge"><small>Day</small>1</span>
              <div>
                <strong>Haridwar</strong>
                <span>Example itinerary</span>
              </div>
            </div>
            <ol>
              {SAMPLE.map((s) => (
                <li key={s.time} className={"tl " + s.kind}>
                  <time>{s.time}</time>
                  <div><span className="tag">{s.label}</span> {s.text}</div>
                </li>
              ))}
            </ol>
            <p className="sample-note">Illustration only. Your plan is built from the places in the data and checked by rules.</p>
          </aside>
        </div>
        <Mountains className="hero-art" />
      </section>

      <section className="stats">
        <div className="container stats-grid">
          {STATS.map(([big, small]) => (
            <div key={small}><strong>{big}</strong><span>{small}</span></div>
          ))}
        </div>
      </section>

      <section id="how" className="section">
        <div className="container">
          <p className="eyebrow">How it works</p>
          <h2 className="section-title">From a rough idea to a booked-ready plan in four steps</h2>
          <ol className="how-grid">
            {STEPS_INFO.map((s, i) => (
              <li key={s.title} className="how-card">
                <span className="how-num">{i + 1}</span>
                <span className="icon-chip"><Icon name={s.icon} size={22} /></span>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="destinations" className="section alt">
        <div className="container">
          <p className="eyebrow">Destinations</p>
          <h2 className="section-title">26 towns, from the Ganga to the Char Dham</h2>
          <div className="dest-grid">
            {DESTINATIONS.map((d) => (
              <button key={d.id} className="dest-card" onClick={onGuest}
                      style={{ "--g1": d.g[0], "--g2": d.g[1] }}>
                <span className="dest-top"><Icon name="pin" size={18} /> Uttarakhand</span>
                <span className="dest-name">{d.name}</span>
                <span className="dest-tag">{d.tagline}</span>
                <span className="dest-chips">{d.tags.map((t) => <i key={t}>{t}</i>)}</span>
              </button>
            ))}
          </div>
          <p className="muted center-text">
            A few favourites. The planner also covers Kedarnath, Auli, the Valley of Flowers, Chopta, Kausani, Mukteshwar, Bhimtal, Lansdowne, Munsiyari and more across Garhwal and Kumaon.
          </p>
        </div>
      </section>

      <section id="features" className="section">
        <div className="container">
          <p className="eyebrow">Why TravelBuddy</p>
          <h2 className="section-title">A planner that shows its working</h2>
          <div className="feat-grid">
            {FEATURES.map((f) => (
              <article key={f.title} className="feat">
                <span className="icon-chip"><Icon name={f.icon} size={22} /></span>
                <h3>{f.title}</h3>
                <p>{f.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section alt">
        <div className="container under">
          <div>
            <p className="eyebrow">Under the hood</p>
            <h2 className="section-title left">Specialist agents, not one big prompt</h2>
            <p className="muted">
              Stay, food, transport and safety agents are plain tested code. The language model only writes the plan,
              a critic validates it, and a human approves it. Answers come from a retrieval graph that grades its own
              evidence and declines when the data is not there.
            </p>
          </div>
          <ul className="stack">
            {STACK.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </div>
      </section>

      <section id="faq" className="section">
        <div className="container narrow">
          <p className="eyebrow">FAQ</p>
          <h2 className="section-title">Good questions</h2>
          <div className="faq">
            {FAQ.map(([q, a]) => (
              <details key={q}>
                <summary>{q}<Icon name="chevron" size={18} /></summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="cta">
        <div className="container cta-inner">
          <h2>Where in Uttarakhand next?</h2>
          <p>No sign-up needed: try it as a guest and get a plan in about a minute.</p>
          <button className="btn-accent lg" onClick={onGuest} disabled={guestBusy}>Plan my trip <Icon name="arrow" size={18} /></button>
        </div>
      </section>

      <footer className="lfoot">
        <div className="container lfoot-grid">
          <Logo onDark height={38} />
          <p>
            Planning aid only. Check weather, road and permit advisories before you travel.
            Data: Wikivoyage (CC BY-SA), OpenStreetMap contributors.
          </p>
        </div>
      </footer>
    </div>
  );
}
