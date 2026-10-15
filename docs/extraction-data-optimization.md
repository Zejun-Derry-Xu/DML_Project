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
