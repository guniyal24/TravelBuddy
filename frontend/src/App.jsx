import { useCallback, useEffect, useState } from "react";
import { clearToken, getToken, guestLogin, isGuest } from "./api.js";
import Auth from "./components/Auth.jsx";
import Chat from "./components/Chat.jsx";
import Icon from "./components/Icon.jsx";
import Landing from "./components/Landing.jsx";
import Logo from "./components/Logo.jsx";
import MyTrips from "./components/MyTrips.jsx";
import Profile from "./components/Profile.jsx";
import ServerStatus from "./components/ServerStatus.jsx";
import Trip from "./components/Trip.jsx";

const TABS = [
  ["trip", "Plan", "compass"],
  ["trips", "My trips", "trips"],
  ["chat", "Ask", "chat"],
  ["profile", "Preferences", "sliders"],
];

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [authMode, setAuthMode] = useState(null); // null | "login" | "register"
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState("trip");
  const [openTrip, setOpenTrip] = useState(null);
  const [online, setOnline] = useState(navigator.onLine);

  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);

  const [guest, setGuest] = useState(isGuest());
  const [guestBusy, setGuestBusy] = useState(false);

  const closeAuth = useCallback(() => { setAuthMode(null); setNotice(""); }, []);
  const logout = () => { clearToken(); setAuthed(false); setGuest(false); setTab("trip"); window.scrollTo(0, 0); };
  const onExpired = () => {
    setAuthed(false);
    setNotice(guest ? "Your guest session ended. Create a free account to keep your trips, or try again as a guest."
      : "Your session expired. Please log in again.");
    setAuthMode(guest ? "register" : "login");
    setGuest(false);
  };
  const go = (t) => { setTab(t); window.scrollTo({ top: 0 }); };
  const signUp = () => { logout(); setAuthMode("register"); };

  async function tryAsGuest() {
    setGuestBusy(true);
    try {
      await guestLogin();
      setGuest(true); setAuthed(true); setAuthMode(null); setNotice(""); setTab("trip");
      window.scrollTo(0, 0);
    } catch (e) {
      setNotice(e.message); setAuthMode("register");
    } finally { setGuestBusy(false); }
  }

  if (!authed) {
    return (
      <>
        <ServerStatus />
        <Landing onLogin={() => setAuthMode("login")} onRegister={() => setAuthMode("register")}
                 onGuest={tryAsGuest} guestBusy={guestBusy} />
        {authMode && (
          <Auth mode={authMode} onMode={setAuthMode} onClose={closeAuth} notice={notice}
                onGuest={tryAsGuest} guestBusy={guestBusy}
                onDone={() => { setAuthed(true); setGuest(false); closeAuth(); }} />
        )}
      </>
    );
  }

  return (
    <div className="app">
      <ServerStatus />
      <header className="appbar">
        <div className="container appbar-in">
          <Logo height={36} />
          <nav className="tabs" aria-label="Main">
            {TABS.map(([id, label, icon]) => (
              <button key={id} className={tab === id ? "tab on" : "tab"} onClick={() => go(id)}
                      aria-current={tab === id ? "page" : undefined}>
                <Icon name={icon} size={18} /> {label}
              </button>
            ))}
          </nav>
          <button className="logout" onClick={logout}><Icon name="logout" size={18} /> <span>{guest ? "Exit guest" : "Log out"}</span></button>
        </div>
      </header>

      {guest && (
        <div className="container">
          <div className="guest-bar" role="status">
            <Icon name="eye" size={18} />
            <span>You're exploring as a guest. Your trips stay available for 24 hours.</span>
            <button className="link" onClick={signUp}>Create a free account</button>
          </div>
        </div>
      )}

      {!online && (
        <div className="container">
          <div className="offline" role="status">
            <Icon name="wifioff" size={18} />
            You are offline. Saved trips stay available under My trips; planning and chat need a connection.
          </div>
        </div>
      )}

      <main className="container main">
        {/* all stay mounted so switching tabs does not lose a half-planned trip */}
        <div hidden={tab !== "trip"}><Trip onExpired={onExpired} initialTrip={openTrip} /></div>
        <div hidden={tab !== "trips"}>
          <MyTrips active={tab === "trips"} onExpired={onExpired}
                   onOpen={(t) => { setOpenTrip(t); go("trip"); }} onPlan={() => go("trip")} />
        </div>
        <div hidden={tab !== "chat"}><Chat onExpired={onExpired} /></div>
        <div hidden={tab !== "profile"}><Profile onExpired={onExpired} /></div>
      </main>

      <footer className="appfoot container">
        Planning aid only. Check weather, road and permit advisories before you travel.
        Data: Wikivoyage (CC BY-SA), OpenStreetMap contributors.
      </footer>

      <nav className="bottomnav" aria-label="Main">
        {TABS.map(([id, label, icon]) => (
          <button key={id} className={tab === id ? "bn on" : "bn"} onClick={() => go(id)}
                  aria-current={tab === id ? "page" : undefined}>
            <Icon name={icon} size={22} /><span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
