export type QuestionOption = {
  value: string;
  label: string;
  description?: string | null;
};

export type Question = {
  question_id: string;
  field: string;
  prompt: string;
  options: QuestionOption[];
  selection_mode: "single";
  allow_free_text: boolean;
  status: string;
  expires_at: string;
};

export type ReturnRequest = {
  id: string;
  rma_number: string;
  status: string;
  created_at: string;
};

export type CaseResponse = {
  session_id: string;
  state: string;
  decision: string | null;
  reason_code: string | null;
  reply: string;
  question: Question | null;
  return_request: ReturnRequest | null;
  request_id: string;
};

export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

