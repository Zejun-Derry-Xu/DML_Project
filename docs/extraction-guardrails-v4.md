# Bounded extraction guardrails v4 — execution record

## Scope and status

This is one repair round, not a model release. Qwen3:4B, policy mvp-2.0.0 and
business API contracts remain unchanged. No cloud actions or local Docker.

Checkpoint 1 contains diagnostic/evaluation tooling and the frozen new data
manifest. It deliberately does not modify the active extractor until the original
frozen comparisons finish or consume their allocation. Completed v3 evidence was
archived on the prior experiment branch; `e32c135` adds the completed 293-turn v2
comparison. Still-running or missing comparisons are not reported as completed.

## Data and protocols

- 48 automatically authored apparel probes: 24 development, 24 sealed validation,
  split by wording family. Labels remain provisional and only masked fields score.
- 96 previously unconsumed ABCD native train conversations: 32 order-only labels,
  32 item-only labels, 32 both. Original train identity and numeric IDs are retained.
- 16 selected conversations / 163 customer turns use actual prior agent questions
  and accumulate only the system's predictions. They are recorded-dialogue replay,
  not closed-loop business end-to-end tests. Gold facts never enter replay state.
- The old 180 apparel samples are regressions. Old customer-only and teacher-forced
  context scores remain separately archived, not relabeled as new blind validation.
- See `tests/fixtures/guardrails_v4_manifest.json` for IDs, exclusion sets and hashes.
  Raw projections and traces remain in the ignored evaluation directory.

## Budget and reproducibility

`scripts.continue_frozen_v3` owns the frozen stage: maximum 9000 seconds.
`scripts.guardrails_budget.RepairBudget` owns subsequent model work: maximum 5400
seconds, never borrowing unused frozen time. The total cap is 14400 seconds.
The shared journal and nonblocking lock prevent overlapping model requests.
Each result is flushed before the next request. Resume checks model/code/data
identity, keeps errors and never repeats completed HTTP smoke to hide a failure.

The pinned weight digest is
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
Use one model, thinking off, context 4096, output 512, total request budget 60s.
Local Apple Metal timing must not be claimed as Jetstream CPU performance.

After the frozen stage reaches an archive boundary, snapshot the unchanged v3
source using `scripts.freeze_v3_snapshot --root PATH`, apply the finite fixes, run
all nonmodel checks, commit the candidate, then run `scripts.run_guardrails_v4`.
Do not run the repair controller against the unfixed checkpoint-1 extractor.
The snapshot generator refuses a source hash other than the verified frozen v3.

## Remaining work and stop rules

- Apply and commit the isolated finite repair patch only after the frozen stage.
- Validate negation, order-role evidence and product-name compatibility via unit,
  API and paired model checks; do not start a second tuning cycle on failures.
- Preserve strict scoring; report order/item independently and retain missing runs.
- Run migration/CI, frontend and real Qwen/HTTP acceptance for the final candidate.
- Publish measured results and remaining limitations, then hand off CPU deployment.

Human label audit and manual cloud acceptance remain release blockers regardless
of aggregate scores. See `results/extraction-guardrails-v4-summary.md` for measured
status and `returnflow-v4-deployment-handoff.md` for diagrams and operating gates.
No main merge, schema downgrade, live restore or volume deletion is authorized.
