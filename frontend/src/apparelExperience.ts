import type { Question } from "./types";

export const FACT_LABELS: Record<string, string> = {
  reason_text: "Return reason (optional)",
  item_name: "Item",
  order_number: "Order",
  stained: "Stains on clothing",
  damaged: "Damage to clothing",
  tags_attached: "Original tags attached",
  tags_intact: "Tags intact and undamaged",
  condition_origin: "When the problem happened",
  used: "Worn or used",
  reported_defect: "Reported defect",
  reported_wrong_item: "Wrong item reported",
};

export function showQuickAnswers(question: Question, degraded: boolean): boolean {
  return degraded || !question.allow_free_text
    || ["order_id", "item_id", "confirm_return", "condition_checklist"].includes(question.field);
}

export function quickAnswerPrompt(question: Question): string {
  // One yes/no card answers exactly one field, never an entire grouped question.
  return question.option_prompt ?? question.prompt;
}

export function quickAnswerLabel(question: Question, answer: string): string {
  return question.allow_free_text
    ? `${quickAnswerPrompt(question)} — ${answer}` : answer;
}
