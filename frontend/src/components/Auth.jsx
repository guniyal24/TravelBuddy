import { useEffect, useRef, useState } from "react";
import { login, register } from "../api.js";
import Icon from "./Icon.jsx";
import Logo from "./Logo.jsx";
import Mountains from "./Mountains.jsx";

// Login / sign-up dialog shown over the landing page.
export default function Auth({ mode, onMode, onClose, onDone, notice }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const first = useRef(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onClose]);

  async function submit(e) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      if (mode === "register") await register(email, password);
      await login(email, password);
      onDone();
    } catch (err) {
      setError(err.message === "SESSION_EXPIRED" ? "Incorrect email or password" : err.message);
    } finally { setBusy(false); }
  }

  const isLogin = mode === "login";
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="auth-title">
        <aside className="modal-art">
          <Logo onDark height={40} />
          <h2>Your Uttarakhand trip, planned in a minute.</h2>
          <ul>
            <li><Icon name="check" size={16} /> Real places, checked for your month</li>
            <li><Icon name="check" size={16} /> Safety notes for altitude and permits</li>
            <li><Icon name="check" size={16} /> Hindi, Hinglish and English</li>
          </ul>
          <Mountains className="modal-mtn" />
        </aside>
        <form className="modal-form" onSubmit={submit}>
          <button type="button" className="icon-btn modal-x" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
          <h1 id="auth-title">{isLogin ? "Welcome back" : "Create your account"}</h1>
          <p className="muted">{isLogin ? "Log in to continue planning." : "It takes a few seconds."}</p>
          {notice && <div className="notice" role="status">{notice}</div>}
          <label>Email
            <input ref={first} type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                   autoComplete="email" placeholder="you@example.com" />
          </label>
          <label>Password
            <input type="password" required minLength={6} value={password}
                   onChange={(e) => setPassword(e.target.value)} placeholder="At least 6 characters"
                   autoComplete={isLogin ? "current-password" : "new-password"} />
          </label>
          {error && <div className="error" role="alert">{error}</div>}
          <button className="primary lg" disabled={busy}>
            {busy ? "Please wait..." : isLogin ? "Log in" : "Create account"}
          </button>
          <button type="button" className="link" onClick={() => onMode(isLogin ? "register" : "login")}>
            {isLogin ? "New here? Create an account" : "Have an account? Log in"}
          </button>
        </form>
      </div>
    </div>
  );
}
