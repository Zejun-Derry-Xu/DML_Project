# ABCD return-intake pilot (2026-09-27)

## Decision

**Partially adopt ABCD for return-intake fact extraction research; do not use it as
ReturnFlow eligibility or end-to-end ground truth.** The current pilot is too small and
imbalanced to justify a production-quality claim. The 28 in-scope first customer requests
support an intent/reason extraction probe. No selected first request stated its order ID,
so the pilot cannot exercise a full return decision.

## Source and reproducibility

- Source: [official ABCD repository](https://github.com/asappresearch/abcd), revision
  `6b8700ce67c6b37b062dd7a60abc76d7ef832a97`,
  [dataset](https://github.com/asappresearch/abcd/blob/master/data/abcd_v1.1.json.gz).
- Source file SHA-256: `2bdf53ac359543dcdc38d55bc6513e78df120363f8f44870716e909f4606de15`.
- The repository states the corpus has `train`, `dev`, and `test` splits and documents its
  conversation/scenario schema. The repository license is MIT. The compressed source and
  derived text/evidence remain local under ignored `data/abcd_pilot/`.
- Selection: for each of `return_size`, `return_color`, `return_stain`, and
  `refund_initiate`, choose the eight lowest `convo_id` values from train and the lowest
  one each from dev and test. This yields 32/4/4 conversations without merging splits.
- Evaluation uses the first customer utterance explicitly containing `return`, `refund`,
  or `send back`; only the utterance, not the scenario label or later turns, is sent to
  the extractor. The script records quoted evidence, character offsets, source, split,
  `convo_id`, and review reason for each candidate field.

```bash
curl -L -o /tmp/abcd_v1.1.json.gz \
  https://raw.githubusercontent.com/asappresearch/abcd/6b8700ce67c6b37b062dd7a60abc76d7ef832a97/data/abcd_v1.1.json.gz
python scripts/abcd_pilot.py /tmp/abcd_v1.1.json.gz
python -m scripts.evaluate_abcd_pilot --provider rules \
  --output docs/results/abcd-pilot-rules.json
python -m scripts.evaluate_abcd_pilot --provider ollama \
  --output docs/results/abcd-pilot-qwen3-4b.json
python -m scripts.evaluate_abcd_pilot --provider hybrid \
  --output docs/results/abcd-pilot-hybrid.json
```

The model runs used local Ollama `qwen3:4b`, model ID `359d7dd4bcda`, with the existing
extractor prompt/schema, temperature zero, and no rule or prompt changes based on dev/test.
These are single runs. Timing is wall time on this Mac and is not a service latency claim.

## Screening and field mapping

| Result | Conversations | Interpretation |
|---|---:|---|
| In-scope, review required | 28 | Explicit initial return request, but insufficient for a complete case. |
| Excluded | 2 | No explicit return/refund request in the selected conversation turns. |
| Out of scope for return eligibility | 10 | `refund_initiate` can involve cancellation before shipment. |

The 38 selected utterances contained 38 explicit request keywords, 14 automatically
identified reason spans, one exact product-name span, and zero utterance-evidenced order
IDs. The scenario's order ID was **not** copied into a customer utterance label. Missing
values remain unknown. `wrong color` was flagged for review because ReturnFlow has no
unambiguous matching reason value; it was not silently mapped to `wrong_item`.

The independently reviewed annotation file labels only `intent` and `reason` for the 28
in-scope utterances. Of those, 14 have a positive reason label. All 28 have an explicit
return intent by the selection rule, so the intent score is a selection sanity check,
not an informative estimate of intent classification quality. The evidence-bearing
local file is `data/abcd_pilot/pilot.json`; the source-free ID/status list is
[`abcd-pilot-manifest.json`](abcd-pilot-manifest.json).

## Extraction results

| Extractor | Intent F1 | Reason precision | Reason recall | Reason F1 | Mean / P95 ms |
|---|---:|---:|---:|---:|---:|
| Existing rules | 1.000 | 0.000 | 0.000 | 0.000 | 0.03 / 0.02 |
| Pure Qwen3:4B | 1.000 | 0.046 | 0.071 | 0.056 | 1173 / 1523 |
| Rules + Qwen | 1.000 | 0.091 | 0.143 | 0.111 | 1073 / 1366 |

The rules missed all 14 independently labeled reasons; typical ABCD wording includes
`wrong size` and `stain`, which the existing ReturnFlow rule phrases do not cover. The
model often mapped `wrong size` to `wrong_item` and emitted a reason for `wrong color`
despite the taxonomy gap. The hybrid inherited most of these errors because the rule
stage left the reason empty. Per-case mismatches and provider failures are in the three
JSON result files. The timing distribution is noisy at this sample size; the reported
P95 is the observed order statistic.

## Suitability and next experiment

- **Fact extraction:** partially useful for first-turn intent and reason coverage, with
  manual review and a taxonomy bridge. Expand only after a second annotator checks the
  labels and the train-only taxonomy changes are frozen. Keep dev/test for final checking.
- **End-to-end return eligibility:** unsuitable as ground truth. ABCD's scenario order
  `purchase_date` is not ReturnFlow's verified `delivered_at`; neither final-sale status
  nor ReturnFlow's ultimate eligibility is provided by these selected utterances.
  ABCD action labels are not policy decisions. Build separate orders and expected final
  database states for an end-to-end experiment.
- **Failure analysis priority:** first handle `wrong size`, stains, and color ambiguity
  on training data, then independently evaluate on untouched dev/test conversations.
  Include negative refund/cancellation controls and multiple user turns before using
  results to guide product behavior.
