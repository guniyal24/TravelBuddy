const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const store = {
  get() { try { return localStorage.getItem("token"); } catch { return null; } },
  set(t) { try { t ? localStorage.setItem("token", t) : localStorage.removeItem("token"); } catch { /* private mode */ } },
};

export const getToken = store.get;
export const clearToken = () => store.set(null);

async function readError(res) {
  if (res.status === 429) return "You're sending requests too fast. Please wait a minute.";
  try { const j = await res.json(); return typeof j.detail === "string" ? j.detail : "Request failed"; }
  catch { return `Request failed (${res.status})`; }
}

async function request(path, { method = "POST", json, form, auth = true, headers: extra = {}, timeoutMs = 150000 } = {}) {
  const headers = { ...extra };
  if (json) headers["Content-Type"] = "application/json";
  if (auth && store.get()) headers.Authorization = `Bearer ${store.get()}`;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(BASE + path, {
      method, headers, body: json ? JSON.stringify(json) : form, signal: ctl.signal,
    });
  } catch (e) {
    if (e.name === "AbortError") throw new Error("This is taking too long. Please try again.");
    throw new Error("Cannot reach the server. Is the backend running?");
  } finally {
    clearTimeout(timer); // the timer only guards getting the response headers
  }
  if (res.status === 401 && auth) { store.set(null); throw new Error("SESSION_EXPIRED"); }
  if (!res.ok) throw new Error(await readError(res));
  return res;
}

export async function register(email, password) {
  await request("/api/register", { json: { email, password }, auth: false });
}

export async function login(email, password) {
  const form = new URLSearchParams({ username: email, password });
  const res = await request("/api/token", { form, auth: false });
  store.set((await res.json()).access_token);
}

export async function startTrip(text) {
  return (await request("/api/trips", { json: { text } })).json();
}

export async function resumeTrip(tripId, value) {
  return (await request(`/api/trips/${tripId}/resume`, { json: { value } })).json();
}

export async function getProfile() {
  return (await request("/api/profile", { method: "GET" })).json();
}
export async function saveProfile(profile) {
  return (await request("/api/profile", { method: "PUT", json: profile })).json();
}
export async function listTrips() {
  return (await request("/api/trips", { method: "GET" })).json();
}
export async function getTrip(id) {
  return (await request(`/api/trips/${id}`, { method: "GET" })).json();
}
export async function setCheck(id, itemId, done) {
  await request(`/api/trips/${id}/checklist`, { method: "PUT", json: { item_id: itemId, done } });
}
export async function replanTrip(id, fromDay, reason) {
  return (await request(`/api/trips/${id}/replan`, { json: { from_day: fromDay, reason } })).json();
}
// format: txt | pdf | ics (ics needs start = YYYY-MM-DD)
export async function exportTrip(id, format, start) {
  const q = new URLSearchParams({ format, ...(start ? { start } : {}) });
  return (await request(`/api/trips/${id}/export?${q}`, { method: "GET" }));
}

// ---- offline copies: the last few opened trips are kept in this browser ----
const KEEP = 8;
function lsGet(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* full or private mode */ } }
export function cacheTrip(trip) {
  if (!trip?.trip_id) return;
  const ids = [trip.trip_id, ...(lsGet("trip-ids") || []).filter((i) => i !== trip.trip_id)].slice(0, KEEP);
  lsSet("trip:" + trip.trip_id, trip);
  lsSet("trip-ids", ids);
}
export function cachedTrips() {
  return (lsGet("trip-ids") || []).map((id) => lsGet("trip:" + id)).filter(Boolean);
}

// Streams the answer text; calls onToken with each decoded chunk.
export async function chat(query, history, sessionId, onToken) {
  const headers = sessionId ? { "X-Session-ID": sessionId } : {};
  const res = await request("/api/chat", { json: { query, history }, headers });
  const sid = res.headers.get("X-Session-ID");
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    onToken(dec.decode(value, { stream: true }));
  }
  return sid;
}
