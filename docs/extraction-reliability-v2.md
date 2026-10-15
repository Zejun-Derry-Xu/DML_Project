# Extraction reliability v2 — implementation and release ledger

Baseline: `6e47091`. New policy: `mvp-2.0.0`. Baseline prompt/schema are frozen in
`app/extractors/legacy.py`; the old eight fields must not be graded against invented
labels for new apparel fields. A valid JSON response is not evidence of semantic correctness.

## Policy contract

Only catalog-classified apparel uses resale-condition checks. Wearing is a fact, not
a rejection reason. All four checks are required: no stains, no item damage, attached
tags, intact tags. Customer-caused adverse conditions reject. Pre-existing problems,
defect/wrong-item claims and unresolved provenance require human review. Missing facts
are questions, not implicit good condition. Non-apparel keeps the original usage policy.
All original delivery/window/final-sale/duplicate safeguards remain. No real refund occurs.

## Evaluation protocol

240 deterministic authored examples, 120 dev / 120 held-out, with disjoint template
families. They are NOT 240 independent real customer conversations. Five catalog-word
substitutions per template test invariance; report both example and template counts.
The labels are assistant-authored and require human review; no public-gold claim.
The first 36 dev examples form the prompt diagnostic subset. Never tune on held-out errors.
Compare frozen legacy, described-schema, then focused/evidence variants serially at
the same model and runtime settings. Keep raw traces ignored and aggregates versioned.
Public ABCD label masks stay unchanged; unannotated apparel fields are unreviewed.

Gate: critical-field macro accuracy >= .90; unsupported fill rate <= paired baseline;
no unsafe approvals; existing supported public labels must be checked for regression.
Human label audit, real-model held-out run, PostgreSQL cloud smoke and restored-backup
exercise are mandatory external gates. An unrun gate is blocked, never a pass.

## Checkpoints

1. Frozen semantics, authored fixture, corrected false-value metrics and baseline.
2. Policy/schema/migration, extraction contracts and multi-turn regression tests.
3. Reproducible private cloud configuration, model evaluation reports and runbook.

No local Docker, parallel model loading, cloud mutation, benchmark gold fabrication,
automatic destructive downgrade, or committing secrets/raw public conversations.
