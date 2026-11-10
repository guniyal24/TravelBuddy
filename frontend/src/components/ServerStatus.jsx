import { useEffect, useState } from "react";
import { ping } from "../api.js";
import Icon from "./Icon.jsx";

const GIVE_UP_MS = 120000;

// Free hosting puts the API to sleep when idle; the first request can take up to a minute.
// Check on load and, if it is asleep, say so (and keep checking) instead of letting the first
// click hang silently.
export default function ServerStatus() {
  const [state, setState] = useState("checking"); // checking | waking | up | down

  useEffect(() => {
    let alive = true;
    const started = Date.now();
    (async () => {
      if (await ping()) { if (alive) setState("up"); return; }
      if (!alive) return;
      setState("waking");
      while (alive && Date.now() - started < GIVE_UP_MS) {
        if (await ping(8000)) { if (alive) setState("up"); return; }
        await new Promise((r) => setTimeout(r, 2000));
      }
      if (alive) setState("down");
    })();
    return () => { alive = false; };
  }, []);

  if (state !== "waking" && state !== "down") return null;
  return (
    <div className="server-status" role="status" aria-live="polite">
      {state === "waking" ? <span className="mini-spin" /> : <Icon name="alert" size={18} />}
      <span>
        {state === "waking"
          ? "Waking up the server. It sleeps when idle on free hosting, so the first load can take up to a minute."
          : "The server is not responding right now. Please try again in a minute."}
      </span>
    </div>
  );
}
