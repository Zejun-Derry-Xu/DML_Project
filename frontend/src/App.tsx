import { FormEvent, useEffect, useRef, useState } from "react";

import { answerQuestion, askPolicy, resumeCase, sendMessage } from "./api";
import type { CaseResponse, ChatMessage, PolicyExplanation, QuestionOption } from "./types";

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
  const [resuming, setResuming] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    localStorage.setItem(SESSION_KEY, sessionId);
    const saved = localStorage.getItem(SESSION_KEY);
    if (!saved) return;
    resumeCase(saved)
      .then((response) => {
        if (!active) return;
        setCurrent(response);
        setMessages((items) => [...items, assistantMessage(response.reply)]);
      })
      .catch(() => undefined)
      .finally(() => { if (active) setResuming(false); });
    return () => { active = false; };
  }, [sessionId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, current]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || !email.trim() || loading || resuming) return;
    setDraft("");
    setMessages((items) => [...items, userMessage(message)]);
    await run(() => sendMessage(sessionId, email.trim(), message));
  }

  async function choose(option: QuestionOption) {
    if (!current?.question || loading || resuming) return;
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
    setResuming(true);
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
        <button className="restart" type="button" onClick={restart} disabled={loading || resuming}>New return</button>
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
          {current && current.policy_evidence.length > 0 && <PolicyEvidence value={current} />}
          {current?.policy_warning && <p className="policy-warning">{current.policy_warning}</p>}
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
              disabled={loading || resuming}
            />
          </label>
          <div className="message-input">
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={terminal ? "Start a new return to continue" : "Describe what you want to return…"}
              disabled={loading || resuming || terminal}
              aria-label="Message"
            />
            <button type="submit" disabled={!draft.trim() || !email.trim() || loading || resuming || terminal}>
              Send <span aria-hidden="true">→</span>
            </button>
          </div>
        </form>
      </section>

      <PolicyHelp />

      <footer>ReturnFlow · Secure demo environment · No real refunds are processed</footer>
    </main>
  );
}

function PolicyHelp() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<PolicyExplanation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || question.trim().length < 3) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await askPolicy(question.trim()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Policy help is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="policy-help" aria-label="Policy help">
      <h2>Questions about our return policy?</h2>
      <p>Ask general policy questions here. This will not change your return or answer its pending question.</p>
      <form onSubmit={submit}>
        <div className="message-input">
          <input aria-label="Policy question" placeholder="What is the return deadline?"
            value={question} onChange={(event) => setQuestion(event.target.value)}
            minLength={3} maxLength={500} disabled={busy} required />
          <button type="submit" disabled={busy || question.trim().length < 3}>
            {busy ? "Searching…" : "Ask policy"}
          </button>
        </div>
      </form>
      {error && <p role="alert">{error}</p>}
      <div aria-live="polite">
        {result && (
          <div className="policy-answer">
            <p>{result.answer}</p>
            <p className="policy-note">Simulated policy · {result.policy_version} · {result.retriever_used}</p>
            {result.citations.length > 0 && (
              <details>
                <summary>View policy sources ({result.citations.length})</summary>
                <ul>{result.citations.map((citation) => (
                  <li key={citation.clause_id}><strong>{citation.clause_id}</strong> {citation.content}</li>
                ))}</ul>
              </details>
            )}
            {result.warning && <p role="status">{result.warning}</p>}
          </div>
        )}
      </div>
    </section>
  );
}

function PolicyEvidence({ value }: { value: CaseResponse }) {
  return (
    <aside className="policy-evidence" aria-label="Policy basis">
      <p className="card-label">POLICY BASIS · {value.policy_version}</p>
      <p className="policy-note">Simulated MVP policy; the return decision is made by verified case rules.</p>
      <ul>
        {value.policy_evidence.map((clause) => (
          <li key={clause.clause_id}>
            <strong>{clause.clause_id}</strong> {clause.content}
          </li>
        ))}
      </ul>
    </aside>
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
