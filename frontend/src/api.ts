import type { CaseResponse, PolicyExplanation } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

type ErrorEnvelope = { error?: { message?: string } };

async function request<T = CaseResponse>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  }).catch(() => { throw new Error("ReturnFlow is temporarily unreachable. Please try again."); });
  const body = (await response.json().catch(() => null)) as (T & ErrorEnvelope) | null;
  if (!response.ok) {
    throw new Error(body?.error?.message ?? "ReturnFlow could not complete the request. Please try again.");
  }
  if (body === null) throw new Error("ReturnFlow sent an incomplete response. Please try again.");
  return body;
}

export function sendMessage(
  sessionId: string,
  customerEmail: string,
  message: string,
  inReplyToQuestionId?: string,
): Promise<CaseResponse> {
  return request("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      customer_email: customerEmail,
      message,
      in_reply_to_question_id: inReplyToQuestionId,
    }),
  });
}

export function answerQuestion(
  sessionId: string,
  questionId: string,
  selectedValue: string,
): Promise<CaseResponse> {
  return request(`/api/v1/questions/${questionId}/answer`, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, selected_value: selectedValue }),
  });
}

export function resumeCase(sessionId: string): Promise<CaseResponse> {
  return request(`/api/v1/return-cases/${sessionId}`);
}

export function askPolicy(question: string): Promise<PolicyExplanation> {
  return request<PolicyExplanation>("/api/v1/policy/ask", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export type DemoCustomer = { id: string; name: string };
export function demoCustomers() { return request<DemoCustomer[]>("/api/v1/demo/customers"); }
export function selectDemoCustomer(customerId: string) {
  return request<DemoCustomer>("/api/v1/demo/session", {
    method: "POST", body: JSON.stringify({ customer_id: customerId }),
  });
}

