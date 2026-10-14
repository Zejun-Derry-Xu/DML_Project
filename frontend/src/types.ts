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

export type PolicyCitation = {
  clause_id: string;
  policy_version: string;
  scope: string;
  content: string;
};

export type CaseResponse = {
  session_id: string;
  state: string;
  decision: string | null;
  reason_code: string | null;
  reply: string;
  question: Question | null;
  return_request: ReturnRequest | null;
  policy_version: string | null;
  policy_evidence: PolicyCitation[];
  policy_warning: string | null;
  request_id: string;
};

export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

export type PolicyExplanation = {
  status: string;
  answer: string;
  policy_version: string;
  citations: PolicyCitation[];
  retriever_used: string;
  generator_used: string;
  warning: string | null;
};
