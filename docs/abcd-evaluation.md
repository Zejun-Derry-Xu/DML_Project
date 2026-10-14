# ABCD ReturnFacts projection

This is a partial, evidence-constrained extraction benchmark over the original public
[Action-Based Conversations Dataset](https://github.com/asappresearch/abcd/tree/6b8700ce67c6b37b062dd7a60abc76d7ef832a97).
It tests the existing ReturnFlow extractors without changing their prompts or rules.
It is **not** ABCD's native action-state-tracking or cascading-dialogue-success score,
and the public data does not directly supply complete ReturnFacts annotations.

The frozen source is `data/abcd_v1.1.json.gz` at revision
`6b8700ce67c6b37b062dd7a60abc76d7ef832a97`, SHA-256
`2bdf53ac359543dcdc38d55bc6513e78df120363f8f44870716e909f4606de15`.
Download provenance is recorded by `scripts/fetch_eval_data.py` in the shared
public evaluation source manifest. Input data, prepared examples and predictions
remain under ignored `data/evaluation_sources/` and `data/evaluation_runs/`.
No files under the unrelated local `data/abcd_synthetic/` are read or changed.

## Preparation and input tasks

Run from the project root using its Python environment:

```sh
.venv/bin/python -m scripts.prepare_abcd
.venv/bin/python -m scripts.evaluate_abcd --provider rules --task all
```

The converter preserves ABCD's native `train`, `dev`, `test` membership and native
`convo_id`. It rejects IDs duplicated within or across splits. There is no resplit.

| Native split | Conversations | Customer-turn inputs | Native `return_*` conversations |
| --- | ---: | ---: | ---: |
| train | 8,034 | 71,259 | 433 |
| dev | 1,004 | 9,096 | 48 |
| test | 1,004 | 9,017 | 57 |

`self_contained` has one input per conversation: original customer messages joined
with newlines in their original order. Agent utterances, actions, scenario metadata,
latent flows/subflows and delexicalized strings are not included in this input.
This task intentionally permits all customer turns in that conversation, so it is
an offline extraction test rather than a simulated first-turn interaction.

`contextual` has one input per original customer turn. Its message is exactly that
turn. The current case contains only earlier grounded customer order/item spans;
the pending field comes from a conservative mapping of the earlier observed agent
request for an order ID or product. Future turns and future action targets are
never used for model input or contextual gold. This is oracle **observed** context,
not a rollout of the extractor's earlier predictions. This distinction prevents
earlier extraction failures from being mistaken for per-turn extraction failures.
The agent text itself is not placed in the extraction message. State values are
context only, matching the production extractor's existing prompt contract.

`--task all` evaluates both tasks, with separate summaries. `--return-only` selects
the native `return_*` metadata slice and all runs additionally report that slice
when selected rows include it. Subflow is used for selection/reporting only; it
never enters the tested model's prompt or supplies a return-intent/reason label.

## Gold policy and coverage

Automatic labels are deliberately limited to these two fields:

1. `order_id`: the official, index-aligned customer delexicalization must contain
   `<order_id>`, and the corresponding native scenario order ID must occur as an
   exact original customer span. A latent or agent-only ID is unreviewed.
2. `item_name`: an original customer span must exactly match an official catalog
   product name, or its product type, allowing case and whitespace/underscore/hyphen
   differences. The expected value is the observed surface span, not an unspoken
   brand or full catalog name. Multiple matching products are ambiguous and masked.
   Full-conversation labels aggregate only consistent product identity and retain
   the longest observed span for that identity.

Each positive label includes its original turn index, span offsets, text, and
annotation basis. These labelers do not call or copy the tested rule extractor.
They rely on ABCD's delexicalization/catalog membership, not ReturnFlow's return,
reason or condition keyword rules. Numeric order IDs remain numeric strings; no
`ORD-` prefix adapter is applied by default. Item values are compared after case/whitespace and
orthographic-separator normalization. There is no fuzzy semantic matching.

| Split | Full-conversation order labels | Full-conversation item labels | Per-turn order labels | Per-turn item labels |
| --- | ---: | ---: | ---: | ---: |
| train | 3,564 | 2,296 | 3,651 | 3,014 |
| dev | 450 | 292 | 457 | 397 |
| test | 438 | 319 | 453 | 435 |

`label_mask: false` means unsupported/unreviewed, not gold null. Automatic labels
do not score `intent`, `reason`, `used`, `opened`, `damaged`, or `wants_human`.
ABCD's latent `return_size`, for example, does not prove that a particular customer
turn explicitly said that the item did not fit. Scenario packaging also does not
prove whether the customer opened the item. Omitted labels cannot establish false
positives or hallucinations. The automatic run's audited hallucination rate is
therefore `null`, not zero, even though it has zero audited absence checks.

The default still evaluates zero-label inputs for latency/provider errors, while
excluding them from accuracy denominators. In the complete test run there are
612 scorable conversations, 1,494 scorable inputs across both tasks, 8,527 unscored
inputs, and 392 conversations with no labels. These are separate counts; correlated
turns are not presented as independent conversations.

Additional slots can be scored with a separately reviewed overlay passed through
`--annotations PATH`. Overlays must declare `projection_version`, `source_revision`,
the pinned `source_sha256`,
`reviewer`, and a list of `annotations`, each with `sample_id`, an explicit
`expected` dictionary and per-field `evidence` containing original customer `text`
spans. Reviewed null/unclear values and `wants_human: false` must also be explicitly
listed in `absence_audited`. Positive condition values, including `used: false`,
need customer evidence. Omitted keys remain unreviewed. The loader rejects missing
evidence, missing absence audits, invalid ReturnFacts values, and duplicate or
unknown sample IDs. Review train/dev before changing label policy; keep test gold
fixed for model comparison. The automatic full-corpus result uses no overlay.

A separate supplement in `tests/fixtures/abcd_reviewed_test_returns.json` contains
twelve **assistant-reviewed, non-official** test return conversations, selected
before individual prediction review by seed 99 and ascending hashed conversation
ID. It includes exact customer evidence, reviewer trace, source checksum, selection
IDs, taxonomy rationale, and audited absence. These supplemental labels need human
confirmation and must not be merged into the official-label main result. They
cover explicit return/fit/color/stain motivations and abstention on unstated
condition fields; none of these twelve customers explicitly asserts use, opening,
or physical damage. Packaging possession/disposal is not sufficient evidence.
One customer never explicitly requests a return and is labeled `unclear`.
Wrong delivered color maps to `wrong_item`; unspecified color dissatisfaction maps
to `other`. A conversation with multiple motivations uses its latest explicit
no-longer-needed motivation. These judgments are disclosed in the fixture for audit.

```sh
.venv/bin/python -m scripts.evaluate_abcd --provider rules --task self_contained \
  --return-only --seed 99 --limit 12 \
  --annotations tests/fixtures/abcd_reviewed_test_returns.json \
  --output data/evaluation_runs/abcd/reviewed-rules-12.jsonl \
  --summary docs/results/public-eval/abcd-reviewed-rules.json
```

## Comparable, bounded local-model runs

Use identical task, split, seed, mask policy and conversation limit for each
provider. `--limit` counts conversations, so a contextual run can contain several
correlated rows per selected conversation. Sampling orders native IDs by a seeded
SHA-256 hash and is independent of source row ordering. `--scorable-only` removes
zero-label rows before conversation sampling and records the excluded count; it
is useful when limiting local-model time.

```sh
.venv/bin/python -m scripts.evaluate_abcd --provider rules --task self_contained \
  --scorable-only --limit 32 --seed 42 \
  --output data/evaluation_runs/abcd/rules-test-self_contained-32.jsonl
.venv/bin/python -m scripts.evaluate_abcd --provider ollama --model qwen3:4b \
  --task self_contained --scorable-only --limit 32 --seed 42 \
  --time-budget-seconds 180 --request-timeout-seconds 30 \
  --output data/evaluation_runs/abcd/ollama-test-self_contained-32.jsonl
.venv/bin/python -m scripts.evaluate_abcd --provider hybrid --model qwen3:4b \
  --task self_contained --scorable-only --limit 32 --seed 42 \
  --time-budget-seconds 180 --request-timeout-seconds 30 \
  --output data/evaluation_runs/abcd/hybrid-test-self_contained-32.jsonl
```

Only localhost Ollama endpoints are supported; no external model API is used.
`ollama` and `hybrid` instantiate the unchanged existing extractors. Sequential
calls avoid competing local GPU work. No retry is configured at the provider
layer. A request timeout and the remaining invocation time budget bound an
in-flight call. Exhaustion is reported as an incomplete run rather than silently
treated as a complete dataset result.

Predictions are appended and flushed after each input. Reuse the same command with
`--resume` to skip completed inputs, including recorded failures. The runner
rejects a mismatched input checksum, configuration or selected sample list.
The time budget is per invocation, so a resumed run can use a larger budget.
Use a new output path to rerun a provider failure intentionally. Outputs are never
overwritten implicitly. `--summary PATH` can place aggregate JSON in a report
directory while keeping raw predictions ignored.

## Metrics and frozen rule result

Per-slot summaries report labeled coverage, correct counts, TP/FP/FN/TN,
precision/recall/F1. A wrong non-null value contributes both FP and FN. Explicit
condition `false` is scored as a fact and never dropped by truthiness filtering.
The schema's default `wants_human: false` is the negative human-request class and
contributes TN when correct; it still participates in annotated-field exact match.
Exact match compares only annotated fields and excludes zero-label rows; provider
errors fail exact match and contribute missed positive labels. Per-conversation
exact match requires all scored selected rows from that conversation to match.
P50/P95 use nearest-rank call latencies including failures. They measure local
extractor invocation, not database/API or total multi-turn workflow latency.

Hallucination is counted only for explicitly audited absence. Predictions in
unreviewed fields are reported separately, without an error claim. Native Ollama
`prompt_eval_count` and `eval_count` are observed through response hooks around
the original extractor. Counts are summed only when both counters are supplied;
unavailable counts are `null`. These are measured token counts, not estimates or
inferred API dollar cost. Hybrid fallback errors can be absorbed by its existing
production behavior; top-level `provider_errors` counts failed extractor calls,
while `model_calls` and `model_attempt_errors` additionally disclose attempted
fallbacks and their failures. The observation wrapper does not change extraction
inputs or the hybrid merge/fallback behavior.

The complete native test run used the frozen production rules on both tasks,
with no ID adapter and no reviewed overlay:

| Metric | Full conversation | Contextual customer turn |
| --- | ---: | ---: |
| Evaluated inputs | 1,004 | 9,017 |
| Scorable inputs | 612 | 882 |
| Independent scorable conversations | 612 | 612 |
| Order ID TP / FN | 0 / 438 | 0 / 453 |
| Item name TP / FP / FN | 3 / 157 / 316 | 26 / 112 / 409 |
| Item name F1 | 0.0125 | 0.0908 |
| Annotated-field exact match | 0.0016 | 0.0295 |
| Provider errors | 0 | 0 |

The order failure exposes a deployment-domain constraint: production rules accept
`ORD-...`, while ABCD uses ten-digit native order identifiers. The result does not
establish that the extractor fails on production-style identifiers. Item exact
span agreement is also low on these longer public conversations. This benchmark
cannot establish return-condition accuracy or a hallucination rate without the
separate reviewed labels described above. Model comparisons and recorded run
latencies belong in the shared public evaluation results report, using the saved
summary JSON and the same frozen selection.

## Separate ID-format compatibility experiment

`--order-id-format mvp` explicitly prefixes only evidence-supported native order IDs
in input and expected output. It clones prepared examples, preserves absent/unknown
fields, and never rewrites source files or introduces latent facts. Default `native`
keeps all main benchmark identifiers unchanged. This adapter is a dataset-format
experiment, not a change to the production extractor.

The rules-only **dev** full-conversation experiment evaluated all 1,004 conversations,
602 with labels. All 450 labeled order IDs were correct after adaptation; item-name
TP/FP/FN were 8/144/284 (F1 0.0360). Labeled slot accuracy was 61.73%, micro F1 0.6815,
and labeled exact match 52.82%. See
[the separate dev report](results/public-eval/abcd-rules-dev-mvp-ids.json).
Do not substitute this adapted dev result for the native test score.

```bash
uv run python -m scripts.evaluate_abcd --provider rules --split dev \
  --task self_contained --order-id-format mvp \
  --output data/evaluation_runs/abcd/my-dev-id-adapter.jsonl \
  --summary docs/results/my-dev-id-adapter.json
```

Paired native 32-case results and the separately labeled reviewed 12-case supplement
are summarized in [the public evaluation report](public-data-evaluation.md).
