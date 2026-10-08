# Local MVP policy retrieval smoke test — 2026-10-08

This is a development smoke test, not an independent benchmark or a measurement of end-to-end
return-case accuracy. All 12 English questions in
[`tests/fixtures/policy_retrieval_questions.json`](../../tests/fixtures/policy_retrieval_questions.json)
were written alongside the implementation. Two were intended to return no clause.

Environment: macOS Apple Silicon, Ollama `embeddinggemma` for embeddings, Qdrant 1.17.1 running
as its official macOS binary bound to `127.0.0.1`, with temporary storage. Docker Desktop would
not launch on this machine, so the standalone binary was used for verification. Its downloaded
archive SHA-256 matched the digest published in the Qdrant 1.17.1 GitHub release metadata. The
optional answer-generation smoke test used local `qwen3:4b`.

| Retrieval configuration | Correct / 12 | Observation |
|---|---:|---|
| Lexical baseline | 12 | Deterministic, no model or vector service |
| Raw vector search, 0.45 score floor | 10 | Missed the broken-product question; returned exchange clauses |
| Prompted EmbeddingGemma, 0.45 floor | 9 | Better exchange abstention, but missed several valid clauses |
| Lexical candidate gate + prompted vector ranking, 0.25 floor | 12 | Correct on this same authored set; **not** a held-out gain |

The final Qdrant query filters by policy version, optional scope, and lexically selected clause
IDs before vector ranking. On the warm local CLI run, supported questions took roughly 12–28 ms
for the embedding/query step; this excludes browser, API startup, and cold model loading.

One live `POST /api/v1/policy/ask` request initially exposed a generation failure: Qwen returned
an analysis-like, incomplete answer despite `think: false`. The generator now requests constrained
JSON, validates length and cited IDs, and falls back to extractive clauses when validation fails.
A subsequent warm API request returned the correct `P-WINDOW` citation with
`retriever_used: qdrant`, `generator_used: ollama`, and no warning. A cold request fell back to
lexical retrieval after the short dependency timeout; the response explicitly reported this.
Another warm API request answered the final-sale question with `P-FINAL-SALE`, using both Qdrant
retrieval and Qwen generation without fallback.

For the case-flow smoke test, the API used a disposable SQLite database seeded with the ten demo
orders; this was **not** a PostgreSQL or Docker deployment test. `ORD-1004` with its matching email
remained `ineligible` / `FINAL_SALE` and returned `P-FINAL-SALE` evidence. `ORD-1010` with its
matching email first asked for usage status and returned `P-USAGE`; after the customer said the item
was unused, the deterministic engine returned `eligible` and `P-APPROVAL`; explicit confirmation
created only a simulated RMA. The evidence is returned in `policy_version` and `policy_evidence`
fields; the React component is wired to render them, but browser rendering was not visually
tested. No vector lookup or model output participates in those case decisions.

This experiment shows that the components can communicate locally and that the guardrail catches
the observed failure. It does **not** establish robust retrieval recall, citation faithfulness on
unseen questions, model safety, load performance, or Jetstream2 deployability. The candidate gate
may miss paraphrases. Next evaluation should freeze the implementation and use a separate held-out
question set with measured abstention, recall@k, citation correctness, and P50/P95 end-to-end
latency. The underlying case decision remains deterministic.
