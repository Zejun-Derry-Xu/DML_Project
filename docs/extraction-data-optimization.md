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
