import { FormEvent, useEffect, useRef, useState } from "react";

import { answerQuestion, resumeCase, sendMessage } from "./api";
import type { CaseResponse, ChatMessage, QuestionOption } from "./types";

const SESSION_KEY = "returnflow-session-id";
const EMAIL_KEY = "returnflow-customer-email";
const welcome: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content: "Hi — I can help with a return. Tell me your order number and what you would like to return.",
};

function newSession(): string {
  return crypto.randomUUID();
}

export default function App() {
  const [sessionId, setSessionId] = useState(
    () => localStorage.getItem(SESSION_KEY) ?? newSession(),
  );
  const [email, setEmail] = useState(() => localStorage.getItem(EMAIL_KEY) ?? "");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([welcome]);
  const [current, setCurrent] = useState<CaseResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    localStorage.setItem(SESSION_KEY, sessionId);
    const saved = localStorage.getItem(SESSION_KEY);
    if (!saved) return;
    resumeCase(saved)
      .then((response) => {
        setCurrent(response);
        setMessages((items) => [...items, assistantMessage(response.reply)]);
      })
      .catch(() => undefined);
  }, [sessionId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, current]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || !email.trim() || loading) return;
    setDraft("");
    setMessages((items) => [...items, userMessage(message)]);
    await run(() => sendMessage(sessionId, email.trim(), message));
  }

  async function choose(option: QuestionOption) {
    if (!current?.question || loading) return;
    setMessages((items) => [...items, userMessage(option.label)]);
    await run(() => answerQuestion(sessionId, current.question!.question_id, option.value));
  }

  async function run(action: () => Promise<CaseResponse>) {
    setLoading(true);
    setError(null);
    try {
      const response = await action();
      setCurrent(response);
      setMessages((items) => [...items, assistantMessage(response.reply)]);
      localStorage.setItem(EMAIL_KEY, email.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  function restart() {
    const next = newSession();
    localStorage.setItem(SESSION_KEY, next);
    setSessionId(next);
    setMessages([welcome]);
    setCurrent(null);
    setError(null);
    setDraft("");
  }

  const terminal = ["return_created", "closed", "escalated", "cancelled"].includes(
    current?.state ?? "",
  );

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="ReturnFlow home">
          <span className="brand-mark" aria-hidden="true">↩</span>
          <span>ReturnFlow</span>
        </a>
        <button className="restart" type="button" onClick={restart}>New return</button>
      </header>

      <section className="hero">
        <p className="eyebrow">RETURN ASSISTANT</p>
        <h1>A smoother way back.</h1>
        <p>Answer only what matters. We check your order and guide you through the rest.</p>
      </section>

      <section className="workspace" aria-label="Return conversation">
        <div className="trust-strip">
          <span><i className="dot" /> Policy-checked decisions</span>
          <span>Your return is not submitted until you confirm</span>
        </div>

        <div className="conversation" aria-live="polite">
          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <div className="avatar" aria-hidden="true">{message.role === "assistant" ? "R" : "You"}</div>
              <p>{message.content}</p>
            </article>
          ))}

          {current?.question && !loading && (
            <div className="question-card">
              <p className="card-label">CHOOSE ONE</p>
              <div className="options">
                {current.question.options.map((option) => (
                  <button type="button" key={option.value} onClick={() => choose(option)}>
                    <strong>{option.label}</strong>
                    {option.description && <span>{option.description}</span>}
                  </button>
                ))}
              </div>
              {current.question.allow_free_text && (
                <p className="free-text-note">You can also type your answer below.</p>
              )}
            </div>
          )}

          {current && terminal && <ResultCard value={current} />}
          {loading && <div className="typing"><span /><span /><span /></div>}
          <div ref={endRef} />
        </div>

        {error && <div className="error" role="alert">{error}</div>}

        <form className="composer" onSubmit={submit}>
          <label>
            <span>Order email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              required
              disabled={loading}
            />
          </label>
          <div className="message-input">
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={terminal ? "Start a new return to continue" : "Describe what you want to return…"}
              disabled={loading || terminal}
              aria-label="Message"
            />
            <button type="submit" disabled={!draft.trim() || !email.trim() || loading || terminal}>
              Send <span aria-hidden="true">→</span>
            </button>
          </div>
        </form>
      </section>

      <footer>ReturnFlow · Secure demo environment · No real refunds are processed</footer>
    </main>
  );
}

function ResultCard({ value }: { value: CaseResponse }) {
  const title = value.state === "return_created"
    ? "Return request created"
    : value.state === "escalated"
      ? "A specialist will review this"
      : value.state === "cancelled"
        ? "Return cancelled"
        : "Return not eligible";
  return (
    <aside className={`result ${value.state}`}>
      <div className="result-icon">{value.state === "return_created" ? "✓" : "i"}</div>
      <div>
        <p className="card-label">RESULT</p>
        <h2>{title}</h2>
        {value.return_request && <p>Reference <strong>{value.return_request.rma_number}</strong></p>}
        {value.reason_code && !value.return_request && (
          <p>Reason code: <code>{value.reason_code}</code></p>
        )}
      </div>
    </aside>
  );
}

function userMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "user", content };
}

function assistantMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "assistant", content };
}
