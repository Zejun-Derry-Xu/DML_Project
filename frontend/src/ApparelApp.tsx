import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { answerQuestion, askPolicy, demoCustomers, resumeCase, selectDemoCustomer, sendMessage } from "./api";
import type { DemoCustomer } from "./api";
import type { CaseResponse, ChatMessage, PolicyExplanation } from "./types";
import { FACT_LABELS, quickAnswerLabel, quickAnswerPrompt, showQuickAnswers } from "./apparelExperience";

const welcome: ChatMessage = {
  id: "welcome", role: "assistant",
  content: "Hi! Tell me what you want to return. A reason is optional. After we find your item, I will show the conditions together — you can confirm them all or tell me just the exceptions. I will check the order and deadline for you.",
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
  const latestMessage = useRef<HTMLElement>(null);
  const checklistStep = useRef<HTMLElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { demoCustomers().then(setAccounts).catch((e: Error) => setError(e.message)); }, []);
  useEffect(() => {
    if (current?.question?.field === "condition_checklist" && !busy) {
      checklistStep.current?.scrollIntoView({ behavior: "auto", block: "start" });
    } else latestMessage.current?.scrollIntoView({ behavior: "auto", block: "start" });
  }, [messages, current, busy]);

  async function select(id: string) {
    setBusy(true); setError("");
    try {
      const user = await selectDemoCustomer(id);
      const key = `returnflow-apparel-${id}`;
      const saved = sessionStorage.getItem(key);
      const next = saved ?? crypto.randomUUID();
      setAccount(user); setSession(next); setCurrent(null); setMessages([welcome]); setDraft(""); setPolicy(null);
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
    if (busy) return false;
    setBusy(true); setError("");
    const outgoingId = crypto.randomUUID();
    setMessages((old) => [...old, { id: outgoingId, role: "user", content: label }]);
    try {
      const result = await action(); setCurrent(result);
      setMessages((old) => [...old, { id: crypto.randomUUID(), role: "assistant", content: result.reply }]);
      return true;
    } catch (e) {
      setMessages((old) => old.filter((message) => message.id !== outgoingId));
      setError(e instanceof Error ? e.message : "Request failed"); return false;
    }
    finally { setBusy(false); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault(); const text = draft.trim();
    if (!text || !account || busy) return;
    if (await run(() => sendMessage(session, "", text, current?.question?.question_id), text)) setDraft("");
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
      <h1>A smoother way back.</h1><p>Tell us the story. We will check the details.</p></section>
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
        {messages.map((m, index) => <article ref={index === messages.length - 1 ? latestMessage : undefined} className={`message ${m.role}`} key={m.id}><p>{m.content}</p></article>)}
        {current?.degraded && <p role="status" className="policy-warning">Natural-language understanding is currently off or unavailable. Review the displayed conditions and use the explicit choices below. We will not guess what a free-text answer means.</p>}
        {current?.question && !["confirm_return", "condition_checklist"].includes(current.question.field) && !busy && <details className="question-card" key={current.question.question_id}
          open={showQuickAnswers(current.question, current.degraded)}>
          <summary>{["order_id", "item_id"].includes(current.question.field) ? "Choose your item or order"
            : current.degraded ? "Quick answers" : "Prefer quick answers?"}</summary>
          <p className="card-label">{quickAnswerPrompt(current.question)}</p>
          <div className="options">{current.question.options.map((o) => <button key={o.value}
            onClick={() => void run(() => answerQuestion(session, current.question!.question_id, o.value), quickAnswerLabel(current.question!, o.label))}>
            <strong>{o.label}</strong>{o.description && <span>{o.description}</span>}
          </button>)}
            {current.question.allow_free_text && !current.degraded && <button onClick={() => input.current?.focus()}>Answer in my own words</button>}
          </div>
          {(current.question.requested_fields?.length ?? 0) > 1 && <p className="free-text-note">These buttons answer only the question immediately above, not all the details in the conversation.</p>}
          </details>}
        {current && Object.keys(current.facts).length > 0 && <details open={current.question?.field === "confirm_return"}>
          <summary>Review reported facts</summary><dl>{Object.entries(current.facts).map(([key, value]) =>
            <div key={key}><dt>{FACT_LABELS[key] ?? key.replaceAll("_", " ")}</dt><dd>{displayFact(value)}</dd></div>)}</dl>
        </details>}
        {!!current?.policy_evidence.length && <details className="policy-evidence"><summary>Policy behind this step</summary>
          {current.policy_evidence.map((c) => <aside key={c.clause_id}>
            <strong>{c.clause_id} · {c.policy_version}</strong><p>{c.content}</p></aside>)}
          </details>}
        {current?.question?.field === "confirm_return" && !busy && <section className="question-card" aria-label="Confirm return">
          <p>Check the summary above before submitting. Nothing has been submitted yet.</p>
          <div className="options">{current.question.options.map((o) => <button key={o.value}
            onClick={() => void run(() => answerQuestion(session, current.question!.question_id, o.value), o.label)}>
            <strong>{o.label}</strong>
          </button>)}</div>
        </section>}
        {current?.support_ticket && <aside className="result-card"><h2>Simulated support ticket</h2>
          <p>{current.support_ticket.id}</p><p>{current.support_ticket.notice}</p></aside>}
        {current?.return_request && <aside className="result-card"><h2>Simulated RMA</h2><p>{current.return_request.rma_number}</p></aside>}
        {busy && <p role="status">Working…</p>}
      </div>
      {current?.question?.field === "condition_checklist" && !busy && <section ref={checklistStep} className="question-card checklist" aria-label="Return conditions">
        <h2>Check these conditions together</h2>
        <p>For <strong>{String(current.facts.item_name ?? "your selected item")}</strong> · {String(current.facts.order_number ?? "")}</p>
        <p>Confirm that none of these problems apply:</p>
        <ul>{current.question.checklist_items?.map((item) => <li key={item.field}>{item.problem}</li>)}</ul>
        <p>You can tell me only the exceptions or what you are unsure about. The confirmation below declares all these problems absent and submits a simulated return request. No money is transferred.</p>
        <div className="options">{current.question.options.map((o) => <button key={o.value}
          onClick={() => void run(() => answerQuestion(session, current.question!.question_id, o.value), o.label)}>
          <strong>{o.label}</strong>
        </button>)}</div>
      </section>}
      {error && <p className="error" role="alert">{error}</p>}
      <form className="composer" onSubmit={(e) => void submit(e)}>
        <p id="return-description-hint" className="composer-hint">Your own words are welcome. Describe what you know; you do not need to know the policy.</p>
        <div className="message-input"><textarea ref={input}
        value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Message" maxLength={4000}
        rows={3} aria-describedby="return-description-hint"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault(); e.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder={terminal ? "Start a new return to continue" : "Tell me about your return…"}
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
    </section><footer>Fictional demonstration only. Customer-reported pre-screening, not physical inspection. No real refunds or external support notifications.</footer>
  </main>;
}
