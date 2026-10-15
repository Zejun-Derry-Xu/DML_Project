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

## Implemented behavior and checks

- `c72de69`: frozen legacy schema/prompt and the authored 240-example fixture.
- `d1450be`: additive migration, apparel policy, evidence envelope, rules/model conflict
  clarification, nullable condition questions, unknown-condition human review and old-case handling.
- `64f845d`: frozen candidate prompt/routing for held-out runs. Subsequent changes to
  reporting, migration import stability and confirmation-version validation do not tune prompts.
- Qwen remains 4B Q4_K_M, digest `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
  Single concurrent request, 4096 context, 512 output cap, thinking off; no new model download.
- Local API smoke passed 32/32 in rules and 32/32 in hybrid. The hybrid trace has
  seven actual model-backed requests and three rule-sufficient requests, not merely configured URLs.
- Tests include 24 condition-state API conversations, explicit confirmation, reload,
  duplicate protection, cross-round conflicts, stale v1 confirmation, migration persistence,
  evidence rejection, transport-only retries and one total timeout budget.
- CI verifies PostgreSQL migrations, Alembic drift, tests and container builds remotely;
  this is not a Jetstream2 model-performance or backup-restore test.
- Final local verification: **223 tests passed**, Ruff/mypy passed, frontend ESLint/build
  passed, standalone cloud Compose configuration parsed without starting Docker.
- Final application smoke: rules 32/32 and Qwen hybrid 32/32. In the synthetic main
  case the observed counts were two unique questions and three user submissions;
  this is measured for one flow, not a claimed usability-study improvement.
- Final non-prompt checks preserve explicit wrong-item corrections during condition
  questions, allow explicit cancellation before confirmation, and reject reuse of an
  answered old-version confirmation. Final rules reproduce all frozen held-out rule outputs.

The exploratory dev ablation precedes the final sparse/focused schema. The original
36-example diagnostic uses 12 dev template groups; it is not representative of all
ambiguity types. Do not present its near-perfect aggregate as a general accuracy claim.
Legacy output lacks the new apparel fields, so common-field claim rates and field-level
counts must accompany any comparison. Missing public labels remain unreviewed.

## Reproduce locally without Docker

Scoring correction: the selected catalog item is supplied in context for this focused
fixture. Raw expected item_name=null means it is not requested, not that no item name
appears in the utterance. The paired common-field claim gate therefore excludes
item_name. Do not present exploratory all-field extra-prediction rates as factual
hallucination rates. Formal field/label review is still required before publication.

```bash
# Fresh synthetic DB; do not delete a user's old demo to make a test pass.
uv run python -m scripts.local_demo --database data/local_demo/returnflow-v2.db
# Optional model mode: start your existing Ollama separately, then:
uv run python -m scripts.local_demo --provider ollama --database data/local_demo/returnflow-v2-model.db
```

Use june@example.com / ORD-1010. For clothing, answer stains, attached tags, intact
tags and item damage; wearing alone does not reject. General policy help can ask
`Can I return worn clothing?` or `What is the return deadline?`. Broad policy-overview
handling remains a separate known limitation; this change does not add a summary intent.

```bash
uv run python -m scripts.evaluate_reliability --variant all --split dev --diagnostic
uv run python -m scripts.evaluate_reliability --variant focused --split test --summary docs/results/local-heldout-focused.json --run-dir data/evaluation_runs/local-heldout-focused
uv run python -m scripts.replay_extraction_incidents
```

Never run model suites concurrently on the 16 GB Mac. Reports contain aggregate
scores; raw output remains ignored. Mac Metal latency is not cloud CPU latency.
Use the separate Jetstream runbook only after all release gates pass.

## Measured held-out result — release remains blocked

The frozen 120-example / 24-template-group supplement gives:

| Mode | Critical-field macro incl. null | Explicit critical-fact macro | Model calls | p50 / p95 (s) |
| --- | ---: | ---: | ---: | ---: |
| Rules | 91.7% | 35.0% | 0 | <0.001 / <0.001 |
| Focused model | 93.7% | 46.0% | 120 | 5.68 / 6.99 |
| Hybrid | 96.3% | 62.0% | 80 | 3.42 / 7.15 |

The legacy schema cannot emit the new fields, so its apparel macro is NOT an
apples-to-apples model-quality baseline. The paired seven-common-field assertion
check excludes out-of-target item_name; the candidate had no unsupported assertions
under these provisional labels. This is not a verified real-world hallucination rate.

Hybrid known-fact counts: stained 25/25, tags_attached 20/25, tags_intact **0/10**,
damaged **3/10**, condition_origin 20/20. Overall known-fact omission is 16.9%; the
field-balanced critical macro is 62%. These metrics have different denominators.
An all-null predictor already scores highly on this sparse fixture, so the overall
90% threshold alone is inadequate. The report additionally blocks release unless
explicit critical-fact macro reaches 90%. We have NOT reached that bar.

Model usage was 110,814 input / 6,820 output tokens in hybrid versus 166,638 / 10,440
in focused-only mode: fewer calls/tokens, not proof of lower cloud monetary cost.
These are local Apple Metal measurements, not Jetstream2 CPU performance.

Next work requires human label review (including focused-vs-full target scope),
then a NEW dev-only investigation of tag integrity and item-damage omissions,
using recorded rejected-evidence fields to distinguish abstention from quote-validation
loss. Do not tune on this held-out set, silently loosen evidence checks, declare
unreviewed labels official gold, or automatically choose a larger model.

Pending before cloud release: a passing known-fact gate, human annotation audit,
Jetstream2/PostgreSQL/CPU-model smoke, and
validated isolated backup restore. CI success does not satisfy those gates.

## Public regression and original incident replay

The same 32 native ABCD conversations (seed 42, 41 official grounded order/item
labels) score 39.02% labeled slot accuracy for both frozen legacy and new model
extraction; micro-F1 is .5079 vs .5333. No new clothing-condition gold was invented.
The full rules regression keeps 10,021 inputs / 1,494 scorable inputs and 1.76%
supported-slot accuracy, unchanged; native numeric IDs remain a documented rules mismatch.

New model-only ABCD p50/p95 is 9.88/18.05 s versus legacy 2.05/2.61 s; tokens are
39,467/6,658 versus 8,865/1,470 (input/output). This semantic/validation scaffolding
does NOT establish a universal accuracy improvement or an efficiency win.

All four original usage examples passed in both direct model and hybrid replay
(8/8). These are known regressions, not independent generalization evidence.
The clothing-policy held-out weaknesses above remain; do not replace them with the
successful incident replay when reporting stakeholder results.
