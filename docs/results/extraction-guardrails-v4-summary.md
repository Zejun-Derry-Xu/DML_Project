# Bounded v4 guardrails — results and deployment handoff

Release: BLOCKED pending human label audit, all quality gates and manual CPU acceptance.
No main merge or Jetstream changes. Qwen3:4B is unchanged; policy is mvp-2.0.0.
Strict ABCD scoring is unchanged. New authored labels are automatically provisional.
Existing 180 apparel examples are regression material, not a new blind test.

| Dataset | Revision | Completed | Explicit apparel macro | Order exact | Item strict | Calls | Input/output tokens | p50/p95 seconds |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| apparel-dev | v3 | NOT RUN | — | — | — | — | — | — |
| apparel-dev | v4 | NOT RUN | — | — | — | — | — | — |
| apparel-validation | v3 | NOT RUN | — | — | — | — | — | — |
| apparel-validation | v4 | NOT RUN | — | — | — | — | — | — |
| apparel-regression | v3 | NOT RUN | — | — | — | — | — | — |
| apparel-regression | v4 | NOT RUN | — | — | — | — | — | — |
| abcd-full | v3 | NOT RUN | — | — | — | — | — | — |
| abcd-full | v4 | NOT RUN | — | — | — | — | — | — |
| abcd-replay | v3 | NOT RUN | — | — | — | — | — | — |
| abcd-replay | v4 | NOT RUN | — | — | — | — | — | — |

## Field diagnostics (reviewed masks only)

| Dataset/revision | Field | Scored | Correct | Evidence rejection | Fusion loss* |
|---|---|---:|---:|---:|---:|

*Fusion loss counts a correct rule field made incorrect by the final result; it does not prove the model alone caused the error. Evidence rejection counts all rejected candidates, not just correct candidates rejected.

## Interpretation boundaries

- ABCD full inputs concatenate customer utterances. Replay uses actual preceding agent questions and only the extractor's own accumulated facts. Neither is closed-loop business end-to-end success.
- Original teacher-forced replay results remain in extraction-optimization-summary.md; do not merge their scores with predicted-history replay.
- Report order and item targets separately (90%/80%). Generic/branded names without a verified unique SKU remain unresolved; no hidden catalog is supplied to ABCD.
- Raw traces remain ignored locally. Full texts and model outputs are not added to operational logs or Git.
- Latencies measured on this Mac's Apple Metal are not Jetstream2 CPU performance. Cold/warm CPU measurements remain pending.
- Missing results, errors and unaudited labels do not authorize release. One repair cycle only; remaining research belongs in backlog.

See ../returnflow-v4-deployment-handoff.md for both diagrams and manual acceptance. No automatic database downgrade, restore-over-live or volume deletion is permitted.
