# Extraction data optimization v3 — execution ledger

Baseline: `6b83c40`; policy remains `mvp-2.0.0`. Work is isolated on
`codex/extraction-data-optimization`, never auto-merged or deployed.

## Frozen protocol

- The v2 prompt, schema, transport, rules and hybrid implementation are retained in
  `app/extractors/frozen_v2/` for paired experiments (only import namespaces changed).
- The old 240 authored examples and already inspected public test examples are
  consumed regression data, not a new holdout.
- The v3 supplement has 120 development and 180 sealed validation inputs, constructed
  from disjoint wording pools. These are authored compositional probes, NOT 300
  independent real customers. Template-family and example counts are reported separately.
- Every supplementary label is automatic/provisional. No human audit, official
  benchmark annotation, or production release approval is implied.
- ABCD retains original source, splits, numeric strings and existing label masks.
  A 192-conversation project reserve is selected from unused native TRAIN conversations
  (64 order-only / item-only / both). Its native split remains train. It is excluded
  from development and never called the official test split. 32 reserve conversations
  are preselected for observed-context per-turn evaluation, not closed-loop task success.
- Only original customer-evidence order/item labels are automatically scored on ABCD;
  missing condition labels are unreviewed, not null gold. Strict normalized equality
  stays the primary metric; span containment is diagnostic, never a substitute score.
- Source hashes, consumed-conversation exclusions and selected reserve IDs are frozen
  in the fixture manifest. Raw source/conversation/model traces remain Git-ignored.

## Execution checkpoints

1. Freeze data and baseline; verify masks, evidence, coverage and selection.
2. Add traceable, scoped extraction and original numeric identifier support.
3. Serial local model comparisons, safety regression, report and remaining blockers.

No Docker or Jetstream mutation, new model, training, multi-agent or RAG infrastructure.
Keep `.env`, raw traces, model weights and unrelated `data/abcd_synthetic/` out of commits.

## Gates

Critical explicit-fact macro >=90%; ABCD order accuracy >=90%, strict item accuracy >=80%.
Report per-field/class counts, false/unknown handling, calls, native token counters,
measured follow-ups, cold/warm latency and provider failures. Unknown/conflicting/
hypothetical/wrong-referent conditions must not lead to automatic approval. Any failed
or unrun gate remains blocked. Even numeric success remains exploratory until label audit.

## Pre-validation data amendment

The original `extraction_optimization_v3.json` and its manifest are archived unchanged.
Development data QA found correlated boolean combinations and a fault-origin sentence
even when every condition was healthy. Before running validation, a separate v3.1
fixture and manifest were frozen. They exercise all 16 combinations of four condition
booleans and omit fault-origin assertions for healthy items. No validation predictions
were used to amend labels. Both versions remain automatic/provisional; the earlier
300 probes are not counted as another independent benchmark.

## Exploratory development experiments (not release scores)

On the original development probes, frozen v2 hybrid scored 67.5% explicit-condition
macro accuracy with 24 unsupported fills. The compact contract with generated literal
quotes scored 84.17%; some otherwise correct candidates failed exact evidence checks.
Selecting original source-fragment IDs avoids quotation rewriting, but initially making
the other conditions optional caused the model to omit them (18.61%). Requiring the
condition group raised pure-model accuracy to 95%, with one provider failure in 120
inputs. Hybrid and the new-rules/frozen-model ablation both scored 100% with 8 model
calls. This does NOT attribute all hybrid gains to the new model prompt: the rules
account for much of that gain. Reports and failed experiments are retained separately.

On the first 48 ABCD development conversations, order labels remained 24/38 for both
hybrids; strict item labels improved from 6/20 to 15/20. Many numeric answers lack an
explicit order cue in customer-only concatenations, and the model often chooses an
alphanumeric account ID. Do not reinterpret account IDs as order IDs, invent cues,
or accept any numeric span solely to pass the score. The 90% order gate is not met.
Observed-dialogue context evaluation is a separate test of available agent questions.

All these exploratory runs used a dirty development tree, not a released candidate.
Runtime source hashes in their reports identify the exact extractor revision. Native
provider counters may be unavailable for failed requests; zero is not proof of free
inference. No cloud latency or PostgreSQL acceptance is inferred from Mac results.

## Frozen candidate and verified progress

Functionality checkpoint `a47065a` is pushed. GitHub CI `38843372273` passed backend
tests, PostgreSQL migrations/schema check/seed, frontend checks and container builds.
Extractor digest: `4281bb8989f6d9bcff75fdd4c54f29dd8f47b9712ad5b007faf9ddb8fa617c3c`.
No local Docker or Jetstream instance was started.

- v3.1 development: rules/hybrid explicit-condition macro 100%; pure model 88.61%
  on 120/120 inputs, zero provider errors and zero audited unsupported fills. The v2
  paired run is still in progress at this checkpoint.
- Frozen validation rules: 93.61% explicit-condition macro on 180 inputs. All-class
  per-field scores: damage 174/180, stains 180/180, attachment 168/180, integrity
  175/180, origin 180/180. No tuning follows inspection of validation predictions.
- ABCD rules evaluated all 10,021 official test projections. The 612 scorable full
  conversations scored order 271/438 (61.87%), item 251/319 (78.68%), both below
  their separate targets. Unlabeled inputs count for cost/errors, not accuracy.
- Project reserve rules: order 72/128, item 97/128. Context rules: order 18/25, item
  19/20 across 32 conversations / 293 turns. Native split remains TRAIN.
- Actual loopback HTTP / fresh SQLite / rules smoke: 32/32 checks, including real
  follow-up counts, citations, confirmation, persistence and duplicate protection.
- Interrupted `dev31-v3-model` results remain partial, separate from the complete run.

## One-shot serial continuation (not a recurring automation)

`scripts.run_optimization_validation --publish --max-hours 4` waits for the existing
development queue, then runs isolated real-Qwen HTTP smoke and all remaining paired
apparel validation / ABCD reserve / official test / contextual comparisons. It uses
one Qwen3:4B allocation, never Docker or cloud. It checks branch, extractor hash,
weights and frozen data, and stops below 10% Mac free-memory percentage. The wall-time
limit is checked between suites; each request retains its own 60-second limit.

Ignored state/PID and log: `data/evaluation_runs/extraction-optimization/serial-status.json`
and `serial-worker.log`. Keep the Mac awake. To stop, read/verify the recorded PID and
send SIGTERM to that worker only. Do not start parallel evaluations. Finished requests
are durable; identical-configuration commands resume or refuse version mismatches.
The worker releases its Qwen allocation at the end without killing unrelated apps.

Completion with `--publish` commits/pushes only owned aggregate reports on this
branch, checking unrelated staged changes; never merges main, deploys, downgrades a
schema or deletes data. A stopped worker retains incomplete/blocked status. A report
commit is evidence publication, not release approval. See the generated
`docs/results/extraction-optimization-summary.md` for actual completion; all unrun,
unmet, human-audit and manual cloud acceptance gates remain blocked.
