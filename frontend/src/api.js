const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const store = {
  get() { try { return localStorage.getItem("token"); } catch { return null; } },
  set(t) { try { t ? localStorage.setItem("token", t) : localStorage.removeItem("token"); } catch { /* private mode */ } },
};

export const getToken = store.get;
export const clearToken = () => store.set(null);

// Reads the (unverified) token payload only to adapt the UI; the server checks the signature.
export function isGuest() {
  const t = store.get();
  if (!t) return false;
  try {
    const b64 = t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(b64)).guest === true;
  } catch { return false; }
}

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

// True if the API answers /health within timeoutMs (free hosts sleep when idle).
export async function ping(timeoutMs = 2500) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try { return (await fetch(BASE + "/health", { signal: ctl.signal })).ok; }
  catch { return false; }
  finally { clearTimeout(timer); }
}

// Try the app without an account: a short-lived guest token.
export async function guestLogin() {
  const res = await request("/api/guest", { auth: false });
  store.set((await res.json()).access_token);
}

// Trip calls. With onEvent, the server streams each agent step (Server-Sent Events) and the
// promise resolves with the same body as the plain JSON call.
async function tripCall(path, json, onEvent) {
  if (!onEvent) return (await request(path, { json })).json();
  const res = await request(`${path}?stream=true`, { json });
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let cut;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
      if (!data) continue; // keep-alive comment
      const ev = JSON.parse(data);
      if (ev.type === "progress") onEvent(ev);
      else if (ev.type === "error") throw new Error(ev.detail || "Planning failed.");
      else if (ev.type === "result") { reader.cancel().catch(() => {}); return ev; }
    }
  }
  throw new Error("The connection dropped while planning. Please try again.");
}

export const startTrip = (text, onEvent) => tripCall("/api/trips", { text }, onEvent);
export const resumeTrip = (tripId, value, onEvent) =>
  tripCall(`/api/trips/${tripId}/resume`, { value }, onEvent);

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
export const replanTrip = (id, fromDay, reason, onEvent) =>
  tripCall(`/api/trips/${id}/replan`, { from_day: fromDay, reason }, onEvent);
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
