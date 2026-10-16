# Extraction optimization — measured progress

Generated 2026-10-16T03:14:12.840398+00:00.

Status: **BLOCKED**. Automatic/provisional labels are not human-audited. Missing runs and unmet gates are not passes. No merge or cloud deployment.

Candidate extractor is frozen at `a47065a`; policy remains `mvp-2.0.0`. Earlier development runs retain their own dirty-tree source hashes. Local Apple Metal timings must not be presented as Jetstream CPU timings.

## Apparel development (120)

| Mode | Completed | Explicit apparel macro | Order exact | Item strict | Unsupported fills* | Model calls | Errors / fallbacks | Native input / output tokens | p50 / p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v2-hybrid | 97/120 PARTIAL | 70.1% | — | — | 13 | 53 | 0 / 0 | 79091 / 7285 | 3.57 / 6.25 |
| v3-rules | 120/120 | 100.0% | — | — | 0 | 0 | 0 / 0 | 0 / 0 | 0.00 / 0.00 |
| v3-model | 120/120 | 88.6% | — | — | 0 | 120 | 0 / 0 | 179512 / 20549 | 5.52 / 6.71 |
| v3-hybrid | 120/120 | 100.0% | — | — | 0 | 8 | 0 / 0 | 11566 / 1579 | 0.00 / 4.80 |

## Apparel validation (180)

| Mode | Completed | Explicit apparel macro | Order exact | Item strict | Unsupported fills* | Model calls | Errors / fallbacks | Native input / output tokens | p50 / p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v2-hybrid | NOT RUN | — | — | — | — | — | — | — | — |
| v3-rules | 180/180 | 93.6% | — | — | 0 | 0 | 0 / 0 | 0 / 0 | 0.00 / 0.00 |
| v3-model | NOT RUN | — | — | — | — | — | — | — | — |
| v3-hybrid | NOT RUN | — | — | — | — | — | — | — | — |

## ABCD project reserve (192 train conversations)

| Mode | Completed | Explicit apparel macro | Order exact | Item strict | Unsupported fills* | Model calls | Errors / fallbacks | Native input / output tokens | p50 / p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v2-hybrid | NOT RUN | — | — | — | — | — | — | — | — |
| v3-rules | 192/192 | — | 56.2% | 75.8% | unreviewed | 0 | 0 / 0 | 0 / 0 | 0.00 / 0.00 |
| v3-model | NOT RUN | — | — | — | — | — | — | — | — |
| v3-hybrid | NOT RUN | — | — | — | — | — | — | — | — |

## ABCD official test (612 scorable full conversations)

| Mode | Completed | Explicit apparel macro | Order exact | Item strict | Unsupported fills* | Model calls | Errors / fallbacks | Native input / output tokens | p50 / p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v2-hybrid | NOT RUN | — | — | — | — | — | — | — | — |
| v3-rules | NOT RUN | — | — | — | — | — | — | — | — |
| v3-model | NOT RUN | — | — | — | — | — | — | — | — |
| v3-hybrid | NOT RUN | — | — | — | — | — | — | — | — |

## ABCD observed context (32 conversations / 293 turns)

| Mode | Completed | Explicit apparel macro | Order exact | Item strict | Unsupported fills* | Model calls | Errors / fallbacks | Native input / output tokens | p50 / p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v2-hybrid | NOT RUN | — | — | — | — | — | — | — | — |
| v3-rules | 293/293 | — | 72.0% | 95.0% | unreviewed | 0 | 0 / 0 | 0 / 0 | 0.00 / 0.00 |
| v3-model | NOT RUN | — | — | — | — | — | — | — | — |
| v3-hybrid | NOT RUN | — | — | — | — | — | — | — | — |

## Interpretation and remaining gates

- The targets are ≥90% explicit apparel macro, ≥90% native order exact, and ≥80% item strict accuracy, reported separately. Partial scores are provisional.
- *ABCD lacks audited absent-condition labels: a zero hallucination count cannot establish zero hallucination risk. Its missing labels stay unreviewed.
- Full-conversation ABCD inputs concatenate customer turns, not agent questions. Some numeric answers are unidentifiable without that missing context. We do not invent order cues or replace native IDs with ORD prefixes to inflate accuracy.
- Context testing supplies the actual preceding agent text. Its prior case facts are teacher-forced observed-label context from the existing projection, not self-accumulated agent state. It is NOT closed-loop end-to-end task success.
- Fixed 4096-token context and 512-token output budgets can limit long inputs; provider failures and rule fallbacks are reported, never dropped from denominators.
- All model work is serial Qwen3:4B, thinking disabled. Native counters exclude any failed transport for which the provider returned no counters.
- Human label audit, paired no-regression checks, all remaining model runs, and manual Jetstream PostgreSQL/API/UI/Qwen acceptance remain required before release.

## Reproduction and rollback

Run from the repository with the pinned official ABCD source/prepared projection and the ignored reserve JSONL available. Select the report's recorded code revision and source/model hashes. Never overwrite reports or change labels after validation.

```bash
.venv/bin/python -m scripts.evaluate_optimization --dataset apparel-v31 --split validation --revision v3 --mode hybrid --name validation31-frozen-v3-hybrid
.venv/bin/python -m scripts.evaluate_optimization --dataset abcd-reserve --revision v3 --mode hybrid --name abcd-reserve-frozen-v3-hybrid
.venv/bin/python -m scripts.evaluate_optimization --dataset abcd-public --revision v3 --mode model --name abcd-public-frozen-v3-model
.venv/bin/python -m scripts.evaluate_optimization --dataset abcd-context --revision v3 --mode hybrid --name abcd-context-frozen-v3-hybrid
.venv/bin/python -m scripts.report_optimization
```

Repeat the same frozen inputs with `v2/hybrid`, `v3/rules`, `v3/model`, and `v3/hybrid` as listed above. One process at a time. Every input is flushed before the next request; the identical command resumes only if its recorded configuration matches. Otherwise choose a new name and retain the old partial result.

Checkpoint 1: `6a44129` (baseline/data); checkpoint 2: `a47065a` (functionality). Main remains unchanged. For application rollback, preserve work and select a reviewed previous code revision; do not reset data, delete volumes, downgrade the schema, or replay a live return. See `docs/jetstream-v2-runbook.md` before any future cloud action.
