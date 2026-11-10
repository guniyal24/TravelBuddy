import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { chat } from "../api.js";
import Icon from "./Icon.jsx";
import { LogoMark } from "./Logo.jsx";

// Answers cite sources as [entity_id]; hide those ids from readers.
const stripIds = (t) => t.replace(/\s*\[[a-z]+(?:_[a-z0-9]+)+\]/g, "");

const SUGGESTIONS = [
  "Where can I eat chole kulche in Haridwar?",
  "Which ashram did the Beatles stay at in Rishikesh?",
  "What can I do in Nainital?",
  "Suggest budget hotels in Haridwar",
];

export default function Chat({ onExpired }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const session = useRef(null);
  const end = useRef(null);

  async function send(q) {
    if (!q.trim() || busy) return;
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "" }]);
    setInput(""); setError(""); setBusy(true); setStatus("");
    let buf = ""; // chunks may split a status marker, so parse from a buffer
    const onChunk = (tok) => {
      buf += tok;
      let text = "";
      for (;;) {
        const a = buf.indexOf("\x01");
        if (a === -1) { text += buf; buf = ""; break; }
        text += buf.slice(0, a);
        const b = buf.indexOf("\x02", a);
        if (b === -1) { buf = buf.slice(a); break; } // incomplete marker, wait for more
        setStatus(buf.slice(a + 1, b));
        buf = buf.slice(b + 1);
      }
      if (text) setMessages((m) => {
        const copy = m.slice();
        copy[copy.length - 1] = { ...copy[copy.length - 1], content: copy[copy.length - 1].content + text };
        return copy;
      });
    };
    try {
      session.current = (await chat(q, history, session.current, onChunk)) || session.current;
    } catch (e) {
      if (e.message === "SESSION_EXPIRED") return onExpired();
      setError(e.message);
      setMessages((m) => m.slice(0, -1));
    } finally { setBusy(false); setStatus(""); setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50); }
  }

  return (
    <section className="chat">
      {messages.length === 0 && (
        <div className="chat-hero">
          <LogoMark size={52} />
          <h1>Ask about Uttarakhand</h1>
          <p className="muted">
            Answers come only from the verified data, with sources. If it does not know, it will say so.
          </p>
          <div className="chips center-chips">
            {SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}
          </div>
        </div>
      )}
      <div className="log" aria-live="polite">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" && <span className="avatar"><LogoMark size={30} /></span>}
            <div className={`bubble ${m.role}`}>
              {m.role === "assistant"
                ? (m.content
                  ? <ReactMarkdown>{stripIds(m.content)}</ReactMarkdown>
                  : <span className="typing"><i /><i /><i /> <span className="muted">{status || "Thinking"}</span></span>)
                : m.content}
            </div>
          </div>
        ))}
        <div ref={end} />
      </div>
      {error && <div className="error" role="alert"><Icon name="alert" size={18} /> {error}</div>}
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question..." aria-label="Your question" />
        <button className="primary" disabled={busy || !input.trim()} aria-label="Send"><Icon name="arrow" size={18} /></button>
      </form>
    </section>
  );
}
