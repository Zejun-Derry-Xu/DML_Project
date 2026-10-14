# Public-data evaluation experiment — 2026-10-14

This branch tests whether public conversations and rule-reading benchmarks can support
ReturnFlow evaluation. It adds offline evaluators, not a new production workflow. The
existing MVP extraction, policy engine, API, and RAG spike are unchanged. Nothing here
performs a real return, deploys to Jetstream2, or starts Docker.

## What is finished

- Pinned public-source downloads, checksum verification, and resumable private checkpoints.
- Automatic evidence-constrained ABCD conversion over all 10,042 conversations.
- Full ABCD test rules evaluation and paired, serial local-model samples.
- Full OR-ShARC test retrieval evaluation and bounded local rule-reading experiments.
- A separate 20-case retail JSON-to-policy boundary supplement with four approaches.
- An isolated official tau2 retail runner with local agent/user models and hard limits.
- A serial suite command, unit/regression tests, and versioned aggregate reports.

Not finished: native ReturnFlow integration into the official tau2 agent interface,
full-corpus LLM evaluation, user usability studies, deployment load tests, and human
confirmation of supplemental ABCD labels. No complete ReturnFlow benchmark score is claimed.

## Data scale and intended use

| Source | Available scale | Use in this experiment |
| --- | ---: | --- |
| [ABCD](https://github.com/asappresearch/abcd) | 10,042 conversations; 89,372 customer turns | Customer language → partially labeled ReturnFacts JSON |
| [OR-ShARC](https://github.com/Yifan-Gao/open_retrieval_conversational_machine_reading) | 21,414 examples; 651 rule documents | Question/history → retrieval → yes/no/clarification and document citations |
| [tau2 retail](https://github.com/sierra-research/tau2-bench/tree/dd8757d4c8791dad7b3cdaf02a105a3d5f9d86bd/data/tau2/domains/retail) | 114 tasks; 1,000 orders | Official multi-turn tools/environment compatibility baseline |
| Authored retail supplement | 20 explicit boundary cases | Verified JSON facts → MVP eligibility decision and policy clause |

Source revisions, download URLs, licenses, and checksums are in
[the source manifest](results/public-eval-source-manifest.json). Data and raw trajectories
stay in ignored `data/evaluation_sources/` and `data/evaluation_runs/`; checked-in reports
contain aggregate metrics. The unrelated existing `data/abcd_synthetic/` is untouched.
[Third-party attribution](evaluation-third-party-notices.md) covers the short ABCD evidence excerpts.

ABCD is **multi-turn**, not a single-turn dataset. Our `self_contained` projection joins
only customer messages for offline extraction; the contextual projection evaluates each
customer turn with earlier observed context. This does not simulate the app asking its own
questions. OR-ShARC supplies observed history and follow-up targets, but the current reader
grades the need to clarify, not the wording or success of a generated follow-up question.
Official tau2 supplies a live user simulator, tools, and state-changing task evaluation.

## 1. ABCD: automatic cleaning is useful, but complete gold cannot be invented

The converter obtains `order_id` and `item_name` only when official metadata and an exact
customer-language span support them. All other fields remain **unreviewed**, not gold null.
There is no model-generated replacement ground truth. This distinction prevents an absent
annotation from being incorrectly counted as a hallucination.

The full native test run covers 1,004 conversations / 10,021 extraction inputs across both
projections. Only 1,494 inputs in 612 conversations have automatic labels; the remaining
8,527 inputs are retained for operational measurements, not accuracy denominators.
See [ABCD methodology](abcd-evaluation.md) and
[full test result](results/public-eval/suite-baseline/abcd-rules-full-test.json).

The rules expect `ORD-…`; ABCD's native numeric IDs expose a format mismatch. A separate
**dev-only compatibility** run prefixes supported IDs without adding semantic facts:
450/450 labeled order IDs become correct. Item span agreement remains poor (F1 0.036).
This experiment is not substituted for the original test result and does not prove
accurate return-reason or condition extraction.

The following comparisons use the same 32 scorable native test conversations, seed 42,
and only the 41 supported order/item labels. Qwen3:4B runs locally, without prompt tuning
on these results. Accuracy means annotated-field accuracy, not all-eight-field accuracy.

| Extractor | Slot accuracy | Micro F1 | Labeled exact match | Input / output tokens | Invocation p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Rules](results/public-eval/abcd-rules-32.json) | 0.00% | 0.0000 | 0.00% | 0 / 0 (no model) | 0.059 / 0.151 ms |
| [Qwen3:4B](results/public-eval/abcd-ollama-32.json) | 39.02% | 0.5079 | 37.50% | 8,865 / 1,470 | 1,392 / 1,759 ms |
| [Hybrid](results/public-eval/abcd-hybrid-32.json) | 26.83% | 0.3235 | 28.12% | 8,865 / 1,470 | 1,373 / 1,762 ms |

All three runs completed; neither model run had provider or fallback-attempt errors.
Hybrid called the model on all 32 inputs, so it saved **no tokens on this sample**. It
merges rule and model output; the lower score motivates investigating rule precedence
and abstention on long, out-of-domain conversations. Do not claim hybrid superiority.

A separately selected 12-conversation return supplement has assistant-reviewed evidence
for all eight fields, with explicit absence audits. These are **non-official labels requiring
human confirmation**, not an extension of official gold. Its slot accuracy is rules 65.62%,
Qwen 71.88%, hybrid 68.75%; exact match is 0% for all. The audited hallucination rates are
3.70%, 20.37%, and 24.07%, respectively. All 36 condition labels are unknown/null, so this
only tests abstention, not accuracy on positive used/opened/damaged facts. Reports:
[rules](results/public-eval/abcd-reviewed-rules.json),
[Qwen](results/public-eval/abcd-reviewed-ollama.json),
[hybrid](results/public-eval/abcd-reviewed-hybrid.json).

## 2. OR-ShARC: retrieval and decision quality must be separate

Frozen BM25 ranks all 651 documents for the complete 2,373-example test split:
Recall@1 **85.97%**, Recall@3 **94.44%**, Recall@5 **96.59%**, full-ranking MRR **0.9047**.
Inputs contain only question, scenario, and observed history; target answers, annotated
evidence, and gold document IDs are withheld from retrieval and reader prompts.

The unchanged local Qwen reader completed a seeded 24-example integrated test sample:
decision accuracy **16/24 (66.67%)**, macro F1 **0.6287**, gold-document citation correctness
**19/24 (79.17%)**, citation document precision **19/31 (61.29%)**. Native token counts:
11,300 input / 1,459 output; query-retrieval-plus-reader latency p50/p95 1,618/2,786 ms.
One output cited an ID outside its supplied context. Document IDs do not establish that
the explanation logically follows from a clause; entailment remains a manual-review task.

The separate 12-example dev comparison completed all 36 calls across oracle, top-1,
and top-3 contexts. All three achieved only 25% decision accuracy despite 100% gold-document
citation correctness. These small samples differ in composition: the higher test score
does not demonstrate improvement from tuning. Full-split retrieval is not full-split LLM
performance. See [methodology and measured reports](or-sharc-evaluation.md).

An optional local embedding retriever uses `embeddinggemma` and exact cosine ranking.
It needs no Qdrant/Docker on this machine. This tests vector ranking, not Qdrant throughput
or production deployment behavior.

The actual full-test embedding run completed all 2,373 queries without errors:
Recall@1 **86.60%**, Recall@3 **94.44%**, Recall@5 **96.63%**, MRR **0.9094**.
Query embedding plus exact ranking p50/p95 was 28.78/35.41 ms; corpus embedding and startup
are excluded from those per-query figures. The full invocation, including corpus embeddings,
took 76.47 seconds and reported 171,870 embedding input tokens. Its 2,394 API calls cover
651 documents in batches and 2,373 queries. This slightly improves top-1 over BM25 but
does not improve Recall@3 on this split. See
[the embedding report](results/public-eval/or-sharc-embeddinggemma-test.json).

## 3. Retail JSON → decision and policy citations

The 20-case supplement has independently listed expected decisions and policy IDs, including
day 30/31, final sale, used items, defects, missing facts, and human review. Fixed time avoids
date-dependent results. Expected answers are never included in retrieval queries or prompts.
This is intentionally **not** a large public benchmark; it checks the MVP's business boundaries.

| Approach | Decision accuracy | Gold clause citation rate | Incorrect approval rate on 14 non-eligible cases | Measured tokens |
| --- | ---: | ---: | ---: | ---: |
| [Rules + reason-code clause](results/public-eval/return-policy-rules.json) | 100% | 100% | 0% | 0 |
| [Rule decision + lexical RAG evidence](results/public-eval/return-policy-hybrid-rag.json) | 100% | 70% | 0% | 0 |
| [Qwen + all policy clauses](results/public-eval/return-policy-llm-full-policy.json) | 30% | 80% | 100% | 11,870 |
| [Qwen + lexical top-3 RAG](results/public-eval/return-policy-llm-rag.json) | 30% | 30% | 78.57% | 7,282 |

The last run recorded two provider/schema errors, retained in the denominator. Both rule
approaches use the **same decision engine**, so equal decision scores are expected; RAG
only supplies evidence. Lexical top-3 retrieved the gold clause in 70% of cases. The model
results do not support delegating eligibility decisions to this small LLM. Correct citation
IDs alone do not certify a correct decision or a faithful explanation.

Supplement latency fields start **after retrieval** and measure only the decision step.
They must not be presented as end-to-end latency. Token totals are local measured counts,
not a dollar bill or a cloud-cost estimate; local execution still consumes hardware/time.

## 4. Official retail workflow: separate runtime, no score conflation

The [tau2 harness](tau2-evaluation.md) uses upstream policy, tools, user simulator, agent,
and scorer in an isolated environment. Its policy differs from ReturnFlow's authored MVP
policy. The generic official agent is a compatibility baseline, **not ReturnFlow itself**.
Tasks with nonempty natural-language assertions (40/114) are explicitly excluded because
their judge would require additional evaluation configuration. No cloud judge is called.
Timeouts, unscored rows, tool limits, and official rewards have separate denominators.

The preselected train task 48 / seed 300 actually ran with 8K context and a 180-second
hard deadline. It timed out after 11 completed steps (12 messages, one tool call), with
**zero scored simulations**. The mean official reward is therefore `null`, not 0 or a
success rate. Partial checkpointed calls recorded 44,482 prompt / 4,737 output tokens;
these exclude an in-flight killed call and are not total task cost. Free-form model output
included lengthy deliberation despite the requested disabled reasoning, often hitting the
512-token cap. The pinned LiteLLM request mapping was separately captured and did send
`think:false`; that setting alone did not guarantee concise model behavior. See
[the measured smoke report](results/public-eval/tau2-smoke.json). Do not scale this configuration
to all tasks before resolving the local model/template behavior on train examples.

## Reproduce safely on a 16 GB Mac

No application server, PostgreSQL, Qdrant, or Docker is required for these offline experiments.
Install the repository Python environment with `uv sync --all-groups`. Start with the full
non-model baseline in the project root:

```bash
uv run python -m scripts.run_public_evaluation --profile baseline \
  --run-name my-baseline --report-dir docs/results/my-baseline
```

For model runs, use an already running Ollama service, or start one in a separate terminal
(do not start a duplicate server on port 11434):

```bash
OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=30s ollama serve
```

After installing `qwen3:4b`, the serial smoke suite prepares data, compares ABCD extractors,
runs 12 dev rule-reading cases, checks the two model retail modes, bootstraps the isolated
tau2 runtime, and attempts task 48. It does not run all models over entire datasets:

```bash
uv run python -m scripts.run_public_evaluation --profile model-smoke \
  --run-name my-smoke --report-dir docs/results/my-smoke
```

Repeat the identical command with `--resume` after an interruption. Budgets yielding partial
runs are recorded, not mistaken for full coverage. Change run/report directories when changing
sample/configuration. Use `--dry-run` to inspect commands without executing them. The baseline
suite and its actual resume path were run successfully; model experiments in this report were
run individually with the same evaluator CLIs, not by replaying the whole smoke suite.

Before a model experiment check `ollama ps` and `memory_pressure`. Only one weight set is
loaded at a time. Qwen used about 3.2 GB with 4K context; the bounded official workflow uses
8K context because its policy plus tool schemas cannot reliably fit 4K. Do not add parallel
inference or Docker to this profile. Unload models when done:

```bash
ollama stop qwen3:4b
ollama stop embeddinggemma
```

If you started `ollama serve` in your terminal, `Ctrl+C` stops that server. These commands
do not stop unrelated services or delete data. For individual source preparation, sampling,
resuming, annotation review, and official-runtime flags, follow the three methodology guides.

## Next decisions supported by the evidence

1. Keep deterministic eligibility decisions and reason-code citations as the safe MVP path.
2. Review the small ABCD annotation overlay; expand evidence-supported reason/condition labels
   on train/dev, keeping test labels frozen and unsupported fields unscored.
3. Investigate numeric-ID support and rule/model merge precedence on dev before a fresh test.
4. Improve relevant-clause retrieval and measure decision and citation quality separately.
5. Implement a replaceable agent/tool adapter before claiming native ReturnFlow tau2 success.
6. Add deployment-facing measures later: task completion, clarification turns, unsafe approvals,
   p95 API latency, concurrent-user behavior, recovery after restart, and resource cost.

The new evaluation modules remain outside the production service path. Public-data preparation,
extractor providers, retrieval, readers, and the official benchmark runtime are separate, so
later adapters or datasets can be added without rewriting the MVP into one benchmark's policy.

## Verification and rollback checkpoints

The final backend regression/unit suite passed 169 tests. Ruff and strict mypy passed for
the application and new evaluation scripts; checked-in result JSON parsed successfully and
local documentation links were checked. One existing FastAPI/Starlette test-client deprecation
warning remains. Frontend and production dependencies were not changed.

The experiment stays on `codex/public-data-eval-2026-10-14`, without merging into the MVP:

- `cd4e0c0`: starting MVP/RAG spike checkpoint.
- `0e60c3a`: pinned public-source downloader and source manifest.
- `25a73ab`: offline evaluation harnesses, fixtures, and tests.
- The following results/documentation commit records the measured outcomes, safe raw-output
  defaults, and this guide.

No Docker container was started. Models were run serially, unloaded after testing, and the
Ollama server started for this experiment was stopped. Cached source files and resumable
trajectories remain on disk, not in Git. The unrelated untracked `data/abcd_synthetic/`
remains excluded from these commits.
