import type { CaseResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

type ErrorEnvelope = { error?: { message?: string } };

async function request(path: string, init?: RequestInit): Promise<CaseResponse> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = (await response.json()) as CaseResponse & ErrorEnvelope;
  if (!response.ok) {
    throw new Error(body.error?.message ?? "ReturnFlow could not complete the request.");
  }
  return body;
}

export function sendMessage(
  sessionId: string,
  customerEmail: string,
  message: string,
): Promise<CaseResponse> {
  return request("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      customer_email: customerEmail,
      message,
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

