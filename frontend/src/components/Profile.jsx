import { useEffect, useState } from "react";
import { getProfile, saveProfile } from "../api.js";
import Icon from "./Icon.jsx";

const EMPTY = { tier: "", diet: "", language: "en", pace: "", origin: "", interests: [], vulnerable_travellers: false };

export default function Profile({ onExpired }) {
  const [p, setP] = useState(EMPTY);
  const [interests, setInterests] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    getProfile().then((d) => { setP({ ...EMPTY, ...d }); setInterests((d.interests || []).join(", ")); })
      .catch((e) => e.message === "SESSION_EXPIRED" && onExpired());
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setP({ ...p, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save(e) {
    e.preventDefault(); setMsg("");
    try {
      const body = { ...p, interests: interests.split(",").map((s) => s.trim()).filter(Boolean) };
      setP({ ...EMPTY, ...(await saveProfile(body)) });
      setMsg("Saved. These are used as defaults for your next trip. Anything you type in a request wins.");
    } catch (err) { err.message === "SESSION_EXPIRED" ? onExpired() : setMsg(err.message); }
  }

  return (
    <form className="card" onSubmit={save}>
      <div className="page-head tight">
        <div>
          <h1>Your travel preferences</h1>
          <p className="muted">The planner remembers these and learns from the trips you approve.</p>
        </div>
      </div>
      <div className="form-grid">
        <label>Budget level
          <select value={p.tier} onChange={set("tier")}>
            <option value="">No default</option><option value="budget">Budget</option>
            <option value="mid">Mid-range</option><option value="premium">Premium</option>
          </select>
        </label>
        <label>Food
          <select value={p.diet} onChange={set("diet")}>
            <option value="">No preference</option><option value="veg">Vegetarian</option>
            <option value="non-veg">Non-vegetarian</option>
          </select>
        </label>
        <label>Pace
          <select value={p.pace} onChange={set("pace")}>
            <option value="">No preference</option><option value="relaxed">Relaxed</option>
            <option value="balanced">Balanced</option><option value="packed">Packed</option>
          </select>
        </label>
        <label>Reply language
          <select value={p.language} onChange={set("language")}>
            <option value="en">English</option><option value="hi">हिन्दी</option>
            <option value="hinglish">Hinglish</option>
          </select>
        </label>
        <label>Travelling from <input value={p.origin} onChange={set("origin")} placeholder="e.g. Delhi" /></label>
        <label>Interests (comma separated)
          <input value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="temples, yoga, food" />
        </label>
      </div>
      <label className="check box">
        <input type="checkbox" checked={!!p.vulnerable_travellers} onChange={set("vulnerable_travellers")} />
        <span>I often travel with children, elderly people or health conditions</span>
      </label>
      {msg && <div className="notice" role="status">{msg}</div>}
      <div><button className="primary lg"><Icon name="check" size={18} /> Save preferences</button></div>
    </form>
  );
}
