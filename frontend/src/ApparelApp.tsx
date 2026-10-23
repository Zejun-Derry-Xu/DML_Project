import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { answerQuestion, askPolicy, demoCustomers, resumeCase, selectDemoCustomer, sendMessage } from "./api";
import type { DemoCustomer } from "./api";
import type { CaseResponse, ChatMessage, PolicyExplanation } from "./types";

const welcome: ChatMessage = {
  id: "welcome", role: "assistant",
  content: "Hi! Describe your clothing return. You can select an order — no order number to remember.",
};

function displayFact(value: unknown): string {
  if (value === null || value === undefined) return "Not provided";
  if (typeof value !== "object") return String(value);
  const fact = value as { state?: string; value?: unknown };
  if (fact.state === "unknown") return "Not sure — review needed";
  if (fact.state === "conflict") return "Conflicting answers — confirm or review";
  if (fact.state !== "known") return "Not yet answered";
  return fact.value === true ? "Yes" : fact.value === false ? "No" : String(fact.value);
}

export default function ApparelApp() {
  const [accounts, setAccounts] = useState<DemoCustomer[]>([]);
  const [account, setAccount] = useState<DemoCustomer | null>(null);
  const [session, setSession] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([welcome]);
  const [current, setCurrent] = useState<CaseResponse | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [policyQuestion, setPolicyQuestion] = useState("");
  const [policy, setPolicy] = useState<PolicyExplanation | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { demoCustomers().then(setAccounts).catch((e: Error) => setError(e.message)); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, current]);

  async function select(id: string) {
    setBusy(true); setError("");
    try {
      const user = await selectDemoCustomer(id);
      const key = `returnflow-apparel-${id}`;
      const saved = sessionStorage.getItem(key);
      const next = saved ?? crypto.randomUUID();
      setAccount(user); setSession(next); setCurrent(null); setMessages([welcome]);
      sessionStorage.setItem(key, next);
      if (saved) {
        try {
          const restored = await resumeCase(saved);
          setCurrent(restored);
          setMessages([welcome, { id: crypto.randomUUID(), role: "assistant", content: restored.reply }]);
        } catch { /* New or expired demo session: no previous case is exposed. */ }
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Account selection failed"); }
    finally { setBusy(false); }
  }

  function restart() {
    if (!account) return;
    const next = crypto.randomUUID();
    sessionStorage.setItem(`returnflow-apparel-${account.id}`, next);
    setSession(next); setCurrent(null); setMessages([welcome]); setDraft(""); setError("");
  }

  async function run(action: () => Promise<CaseResponse>, label: string) {
    if (busy) return;
    setBusy(true); setError("");
    setMessages((old) => [...old, { id: crypto.randomUUID(), role: "user", content: label }]);
    try {
      const result = await action(); setCurrent(result);
      setMessages((old) => [...old, { id: crypto.randomUUID(), role: "assistant", content: result.reply }]);
    } catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setBusy(false); }
  }

  function submit(e: FormEvent) {
    e.preventDefault(); const text = draft.trim();
    if (!text || !account || busy) return;
    setDraft(""); void run(() => sendMessage(session, "", text), text);
  }

  async function queryPolicy(e: FormEvent) {
    e.preventDefault(); if (!policyQuestion.trim() || busy) return;
    setBusy(true); setError("");
    try { setPolicy(await askPolicy(policyQuestion)); }
    catch (e) { setError(e instanceof Error ? e.message : "Policy unavailable"); }
    finally { setBusy(false); }
  }

  const terminal = current?.read_only || ["return_created", "closed", "escalated", "cancelled"].includes(current?.state ?? "");
  return <main className="shell">
    <header className="topbar"><a className="brand" href="/">↩ ReturnFlow</a>
      <button className="restart" onClick={restart} disabled={busy || !account}>New return</button></header>
    <section className="hero"><p className="eyebrow">APPAREL RETURN ASSISTANT</p>
      <h1>A smoother way back.</h1><p>Fictional accounts. Customer-reported pre-screening, not physical inspection.</p></section>
    <section className="policy-help">
      <label>Demo account (not real authentication) <select aria-label="Demo account" disabled={busy}
        value={account?.id ?? ""} onChange={(e) => void select(e.target.value)}>
        <option value="" disabled>Select a fictional account</option>
        {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select></label>
    </section>
    <section className="workspace" aria-label="Return conversation">
      <div className="trust-strip"><span>Policy-checked decisions</span><span>Nothing submitted until you confirm</span></div>
      <div className="conversation" aria-live="polite">
        {messages.map((m) => <article className={`message ${m.role}`} key={m.id}><p>{m.content}</p></article>)}
        {current?.degraded && <p role="status" className="policy-warning">Language extraction is unavailable. Use the cards; unresolved information goes to simulated support.</p>}
        {current?.question && !busy && <div className="question-card">
          <p className="card-label">{current.question.prompt}</p>
          <div className="options">{current.question.options.map((o) => <button key={o.value}
            onClick={() => void run(() => answerQuestion(session, current.question!.question_id, o.value), o.label)}>
            <strong>{o.label}</strong>{o.description && <span>{o.description}</span>}
          </button>)}
            {current.question.allow_free_text && <button onClick={() => input.current?.focus()}>Other — type an answer</button>}
          </div></div>}
        {current && Object.keys(current.facts).length > 0 && <details open={current.question?.field === "confirm_return"}>
          <summary>Review reported facts</summary><dl>{Object.entries(current.facts).map(([key, value]) =>
            <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{displayFact(value)}</dd></div>)}</dl>
        </details>}
        {current?.policy_evidence.map((c) => <aside key={c.clause_id} className="policy-evidence">
          <strong>{c.clause_id} · {c.policy_version}</strong><p>{c.content}</p></aside>)}
        {current?.support_ticket && <aside className="result-card"><h2>Simulated support ticket</h2>
          <p>{current.support_ticket.id}</p><p>{current.support_ticket.notice}</p></aside>}
        {current?.return_request && <aside className="result-card"><h2>Simulated RMA</h2><p>{current.return_request.rma_number}</p></aside>}
        {busy && <p role="status">Working…</p>}<div ref={end} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <form className="composer" onSubmit={submit}><div className="message-input"><input ref={input}
        value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Message" maxLength={4000}
        placeholder={terminal ? "Start a new return to continue" : "Describe your return or answer in your own words…"}
        disabled={!account || busy || !!terminal} /><button disabled={!account || busy || !!terminal || !draft.trim()}>Send →</button></div></form>
    </section>
    <section className="policy-help"><h2>Questions about our apparel policy?</h2>
      <p>This read-only lookup does not answer the pending return question.</p>
      <form onSubmit={(e) => void queryPolicy(e)}><div className="message-input">
        <input aria-label="Policy question" value={policyQuestion} maxLength={500} minLength={3}
          onChange={(e) => setPolicyQuestion(e.target.value)} placeholder="What is the return deadline?" />
        <button disabled={busy || policyQuestion.trim().length < 3}>Ask policy</button></div></form>
      {policy && <div><p>{policy.answer}</p><p>{policy.policy_version} · {policy.generator_used}</p>
        {policy.citations.map((c) => <p key={c.clause_id}>{c.clause_id}: {c.content}</p>)}
        {policy.warning && <p role="status">{policy.warning}</p>}</div>}
    </section><footer>Fictional demonstration only. No real refunds or external support notifications.</footer>
  </main>;
}
