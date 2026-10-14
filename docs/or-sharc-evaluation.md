# OR-ShARC retrieval and rule reasoning evaluation

This benchmark measures retrieval of public rule text, reasoning with known and missing facts,
and document citation correctness. It is independent of ReturnFlow's authored retail rules:
the evaluator uses the original OR-ShARC rule corpus and conversations. It does not replace
the separate retail policy tests.

The dataset comes from the authors'
[OR-ShARC repository](https://github.com/Yifan-Gao/open_retrieval_conversational_machine_reading/tree/309c4ea3a7cc4c7a815d7f46292d91fc9a0de581).
The [technical report](https://arxiv.org/abs/2102.08633) describes the task. The upstream README
attributes the dataset to ShARC and specifies CC BY-SA 3.0 redistribution. Source files are
pinned at commit `309c4ea3a7cc4c7a815d7f46292d91fc9a0de581`; the downloader records URLs,
checksums, license, and verification time in a manifest. Data are never pulled from a moving
branch during evaluation.

## Data and leakage controls

The official files named `open_retrieval_sharc_{train,dev,test}.json` are JSONL, not JSON
arrays. There are 17,936 train examples, 1,105 dev examples, 2,373 test examples, and 651 rule
documents in `id2snippet.json`. The loader validates types, unique utterance IDs, and the
existence of each gold document in the corpus. It refuses a changed source checksum.

Only `question`, `scenario`, and the observed `history` are retrieval/model inputs. Target
fields `answer`, `gold_snippet_id`, and `evidence` are explicitly excluded. `evidence` contains
annotated facts extracted from the scenario, so supplying it would leak ground truth.
`source_url`, `tree_id`, `snippet_seen`, and any extra source fields are also excluded.
Oracle reading supplies only the gold public rule text and its ordinary document ID.

Answers `Yes` and `No` become `yes` and `no`; follow-up questions become `inquire`. An
`Irrelevant` target is rejected rather than silently mapped into this three-class task.
Question generation quality is not automatically graded. A `tree_id` identifies a shared
rule/question group; several conversation paths can have the same group. Reports therefore
include utterance counts, unique tree groups, distinct gold documents, and seen/unseen counts.
The full test split contains 428 tree groups and 423 distinct gold documents.

## Experiments

| Component | Input rule context | What the comparison isolates |
| --- | --- | --- |
| Retrieval | All 651 documents | Whether the relevant rule is retrieved |
| Reader oracle | Gold public snippet | Reading and decision making with a relevant rule |
| Reader retrieved | BM25/vector top-1 snippet | Effect of retrieval failure on the same reader |
| Integrated | BM25/vector top-3 snippets by default | Question/history → retrieval → rule reasoning and citations |

The lexical baseline implements Okapi BM25 with fixed `k1=1.2`, `b=0.75`, lowercase ASCII
alphanumeric tokens, unique query terms, and ID ordering for score ties. The query concatenates
the question, scenario, and each observed follow-up question and answer. It ranks every document;
there is no gold-aware candidate filter or policy-specific vocabulary. MRR uses the complete
ranking, not a top-5 approximation. No test failures were used to tune this baseline.

The optional vector backend calls the local Ollama embedding API and ranks normalized vectors
by exact cosine similarity. It requires no Qdrant instance or extra numerical library. Corpus
vectors are cached privately and tied to the model name and exact corpus text; model digests
are recorded and checked when resuming. `embeddinggemma` gets document/query task prefixes.
Embedding cost is reported per invocation; cached document vectors do not incur new calls.

The reader calls Ollama's native `/api/chat` with `think:false`, temperature 0, a fixed seed,
and a JSON schema. Its output is `decision`, a concise `answer`, and `evidence_ids`. Extra keys,
unknown decision labels, empty answers, and duplicate citations fail schema validation. A
well-formed citation to an unavailable document remains observable as an out-of-context citation
and is scored against the gold document; it does not gain credit for looking like an ID.
Only local HTTP endpoints on `localhost`, `127.0.0.1`, or `::1` are permitted. There is no cloud
inference, model training, or model-generated replacement ground truth.

## Frozen lexical results, 2026-10-14

| Split / subset | Examples | Recall@1 | Recall@3 | Recall@5 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Test, complete | 2,373 | 85.97% | 94.44% | 96.59% | 0.9047 |
| Test, seen | 1,000 | 84.30% | 92.30% | 94.70% | 0.8874 |
| Test, unseen | 1,373 | 87.18% | 95.99% | 97.96% | 0.9174 |
| Dev, complete | 1,105 | 85.07% | 92.13% | 94.48% | 0.8929 |
| Dev, seen | 500 | 84.60% | 94.00% | 95.80% | 0.8965 |
| Dev, unseen | 605 | 85.45% | 90.58% | 93.39% | 0.8900 |

Both runs completed without errors. Test retrieval latency was p50 0.400 ms / p95 0.537 ms;
dev was p50 0.395 ms / p95 0.537 ms. These measurements cover query ranking, excluding
source loading, BM25 index construction, JSONL checkpoint writes, and any model initialization.
They are specific to this local run, not deployment throughput claims. Aggregate reports:
[test](results/or-sharc-bm25-test-2026-10-14.json) and
[dev](results/or-sharc-bm25-dev-2026-10-14.json).

These are full-split retrieval measurements. A local reader result must separately identify
its fixed sample size and completion status; it must not be presented as full-split model
performance or as a reproduction of the paper's models.

## Frozen local vector result, 2026-10-14

The optional `embeddinggemma` backend was also run on all 2,373 test examples and the
same 651 documents. Exact cosine ranking achieved Recall@1 86.60%, Recall@3 94.44%,
Recall@5 96.63%, and MRR 0.9094, with no retrieval errors. Query embedding plus exact
ranking latency was p50 28.78 ms / p95 35.41 ms, excluding corpus embedding and startup.
The full invocation took 76.47 seconds; 2,394 local embedding calls processed 3,024
inputs (651 documents in batches plus 2,373 queries) and reported 171,870 input tokens.
There were no generation calls. Model digest and source/code hashes are included in
[the aggregate vector report](results/public-eval/or-sharc-embeddinggemma-test.json).

Top-1 improves slightly over lexical BM25 while Recall@3 is identical. This is a retrieval
comparison, not evidence of improved final decisions. Exact in-process ranking does not
measure Qdrant deployment performance. The single embedding model occupied about 673 MB
in `ollama ps`; it was run after unloading Qwen, with no Docker or simultaneous model.

## Local Qwen reasoning results, 2026-10-14

The frozen evaluator ran `qwen3:4b` (Q4_K_M) locally with active runtime context length 4,096,
temperature 0, `think:false`, 220 maximum generated tokens, and sample seed 42. The model digest
was `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
The 12-example dev sample covered 10 tree groups, 5 seen and 7 unseen examples. All 36 paired
and integrated dev calls completed in 61.68 seconds. Without changing the prompt, retrieval
parameters, or model, the 24-example test sample covered 21 tree groups, 15 seen and 9 unseen
examples; all 24 integrated calls completed in 43.88 seconds. Both runs had zero provider,
timeout, or schema errors, and native token counts were available for every call.

| Split / condition | Examples | Decision accuracy | Macro F1 | Gold-document citation correctness | Citation document precision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dev, oracle rule | 12 | 25.00% (3/12) | 0.2222 | 100.00% | 100.00% |
| Dev, retrieved top-1 | 12 | 25.00% (3/12) | 0.2222 | 100.00% | 100.00% |
| Dev, integrated top-3 | 12 | 25.00% (3/12) | 0.2500 | 100.00% | 60.00% (12/20 citations) |
| Test, integrated top-3 | 24 | 66.67% (16/24) | 0.6287 | 79.17% (19/24) | 61.29% (19/31 citations) |

| Split / condition | Measured prompt tokens | Measured output tokens | Latency p50 | Latency p95 |
| --- | ---: | ---: | ---: | ---: |
| Dev, oracle rule | 3,710 | 781 | 1,417.70 ms | 2,949.16 ms |
| Dev, retrieved top-1 | 3,710 | 781 | 1,224.90 ms | 2,739.35 ms |
| Dev, integrated top-3 | 5,256 | 961 | 1,824.12 ms | 3,290.92 ms |
| Test, integrated top-3 | 11,300 | 1,459 | 1,618.27 ms | 2,785.99 ms |

The dev sample illustrates why document correctness cannot certify a decision: even oracle
context and correct citations yielded only 3 correct decisions, and all 3 gold `inquire`
examples were classified `no`. In the test sample, the reader correctly classified 10 of 11
`inquire` examples but only 3 of 7 `yes` and 3 of 6 `no` examples. One test answer cited an ID
outside its supplied context. This is evidence of varying behavior on small samples, not an
improvement caused by dev tuning. Test seen accuracy was 8/15 and unseen accuracy 8/9; these
small subsets should not support broad generalization claims. Textual entailment and faithfulness
were not automatically scored.

Aggregate reports with complete confusion matrices, seen/unseen breakdowns, source/model
provenance, and exact sample fingerprints:
[dev-12](results/public-eval/or-sharc-qwen-dev12.json) and
[test-24](results/public-eval/or-sharc-qwen-test24.json). Full split BM25 results repeated within
these model reports match the frozen lexical baseline. Raw contexts, responses, and decisions
remain in the ignored checkpoints, with no source conversation text in the aggregate reports.

## Run and resume

From the project directory, download pinned sources first:

```bash
uv run python -m scripts.fetch_eval_data --dataset or_sharc
```

The evaluator expects the files and `manifest.json` under `data/evaluation_sources/or_sharc/`.

Run the complete frozen retrieval baseline:

```bash
uv run python -m scripts.evaluate_or_sharc --mode retrieval --split test \
  --run-dir data/evaluation_runs/or_sharc/my-bm25-test \
  --summary docs/results/my-bm25-test.json
```

Run all three reasoning conditions on a single label-independent dev sample:

```bash
uv run python -m scripts.evaluate_or_sharc --mode all --split dev \
  --model qwen3:4b --sample-size 12 --seed 42 --top-k 3 \
  --timeout-seconds 90 --time-budget-seconds 600 \
  --run-dir data/evaluation_runs/or_sharc/my-reader-dev \
  --summary docs/results/my-reader-dev.json
```

`--mode reader` runs oracle and retrieved top-1 conditions; `--mode integrated` runs retrieved
top-k only. Retrieval always covers the entire requested official split, even when reasoning
uses a small sample. `--retriever ollama --embedding-model embeddinggemma` enables exact vector
retrieval. Run embedding and reader experiments serially on one local model server when CPU or
memory are shared.

Sampling uses sorted utterance IDs and a seeded uniform sample without inspecting labels.
The same selected examples are reused across contexts. Calls are interleaved by example to
keep bounded runs paired. `--limit` caps new model calls, not selected examples; `--time-budget-seconds`
caps the invocation and reduces HTTP timeouts to the remaining budget. To continue, repeat
the same command with `--resume` and the exact `--run-dir`. Limit and budget may change;
sample, sources, model digest, prompt, retrieval settings, and evaluator code must match.
Completed error records remain counted and are not silently retried or dropped.

Each run writes its manifest and complete prediction records under ignored
`data/evaluation_runs/`. A truncated final JSONL line from an interrupted append is removed on
resume; earlier complete records are retained. Raw reader records preserve the user inputs,
supplied rule documents, full native Ollama response, predictions, native token counts, error
type, and latency. Public `docs/results/` JSON files contain aggregate metrics and provenance,
not source conversations. Source data are also ignored and can be reconstructed from their
pinned manifest.

## Interpretation and denominators

Retrieval reports Recall@1/3/5, full-ranking MRR, planned and attempted counts, errors, p50/p95
latency, and seen/unseen breakdowns. Not-run retrieval cases contribute zero to selected-split
metrics, so completion status matters.

Reasoning reports decision accuracy, three-class macro F1 and confusion matrices, citation
document precision, gold-document citation correctness, out-of-context citation counts,
timeouts/provider/schema errors, token totals, and p50/p95 latency. It gives metrics on both
all selected cases and attempted cases. Failed calls count as incorrect in attempted metrics;
not-run cases also count as incorrect in selected metrics. Selected accuracy is a lower bound
until completion; partial-run macro F1 remains provisional. Fixed three-class F1 assigns zero
to a class with neither gold nor predicted examples in a small sample.

Citation precision counts correct gold document IDs divided by all returned document IDs.
Gold-document correctness counts examples citing the gold document divided by the stated
example denominator. Neither metric demonstrates clause entailment, logical consistency, or
textual faithfulness. Those claims need manual review of the privately saved context and answer.
Native `prompt_eval_count` and `eval_count` are reported as measured tokens only when supplied;
missing counts stay unknown. Integrated latency adds the retrieval query latency to reader
latency, excluding corpus indexing and startup. Paired reader reports use the intersection of
attempted oracle/retrieved cases and retain failed calls in their denominator.

Validation covers the official JSONL shape, gold leakage, missing-facts labels, deterministic
ranking/sampling, complete-rank MRR, schema failures, native token preservation, timeout/error
denominators, vector ranking, source checksums, and interrupted resume. The initial evaluator
passed 29 unit tests, Ruff, and strict mypy checks.
