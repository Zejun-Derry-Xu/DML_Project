import assert from "node:assert/strict";
import test from "node:test";
import { quickAnswerLabel, quickAnswerPrompt, showQuickAnswers } from "../src/apparelExperience.ts";

const grouped = {
  field: "stained", allow_free_text: true,
  prompt: "Describe the clothing and tags together.",
  option_prompt: "Does the clothing have any stains?",
  requested_fields: ["stained", "damaged", "tags_attached", "tags_intact"],
};

test("natural language is primary, with optional rather than forced cards", () => {
  assert.equal(showQuickAnswers(grouped, false), false);
});

test("degraded mode keeps a usable visible card fallback", () => {
  assert.equal(showQuickAnswers(grouped, true), true);
});

test("selection and explicit confirmation remain visible", () => {
  for (const field of ["order_id", "item_id", "confirm_return"]) {
    assert.equal(showQuickAnswers({ ...grouped, field, allow_free_text: false }, false), true);
  }
});

test("yes/no controls name their one field, not the grouped prompt", () => {
  assert.equal(quickAnswerPrompt(grouped), "Does the clothing have any stains?");
  assert.equal(quickAnswerLabel(grouped, "No"), "Does the clothing have any stains? — No");
});

test("older API questions remain readable", () => {
  assert.equal(quickAnswerPrompt({ prompt: "Is it damaged?" }), "Is it damaged?");
});

test("a condition checklist is visible even when language understanding is off", () => {
  const checklist = { ...grouped, field: "condition_checklist" };
  assert.equal(showQuickAnswers(checklist, false), true);
  assert.equal(showQuickAnswers(checklist, true), true);
});
