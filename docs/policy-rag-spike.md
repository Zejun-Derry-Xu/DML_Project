# MVP policy retrieval spike

This branch adds a small, read-only policy question-answering path and cited policy evidence on
case responses. It is an experiment, not a production policy service or a replacement for the
deterministic return decision engine.
The source of truth is the versioned English policy document at
[`app/policy/data/mvp-1.0.0.json`](../app/policy/data/mvp-1.0.0.json). Its clauses describe only the
rules already implemented by the MVP. Each clause has a stable ID, scope, and applicable reason
codes. There is no retailer-specific source policy in this repository, so these are explicitly
simulated MVP rules, not real store terms.

```text
General policy question -> /api/v1/policy/ask
  -> lexical retriever (default) OR lexical candidate gate -> Ollama embedding -> Qdrant search
  -> version/scope-filtered policy clauses
  -> extractive answer (default) OR optional Ollama wording
  -> clause IDs, exact quoted source content, policy version

Return-case conversation -> trusted order facts -> deterministic policy engine -> simulated RMA
                                            |-> reason code -> exact policy clause citation
```

No policy indexing occurs during API startup or a user request. The optional Qdrant collection is
created by an explicit indexing command. The API retrieves only current-version clauses, and the
response renders text from the local canonical document, not arbitrary vector-store payload. If
the optional vector or generation service is unreachable, the endpoint falls back to lexical
retrieval or extractive wording and reports that in `retriever_used` / `generator_used` and
`warning`. Questions containing an MVP order ID are directed to the case flow rather than answered
as if policy retrieval could verify an order. Case responses use the engine's verified reason code
to attach exact clauses from the same document; they do not call a model or Qdrant. This keeps
return decisions independent of vector-service availability.
If the local policy document itself cannot be read, the existing case decision still returns and
`policy_warning` explains why citations are absent.

EmbeddingGemma indexing uses its recommended document/query prefixes. Before Qdrant search, the
experimental semantic path requires a lexical policy candidate and filters Qdrant on candidate
clause IDs plus policy version and optional scope. This conservative gate avoids unsupported
topics receiving plausible but unrelated vector hits, at the cost of missing paraphrases that the
lexical step does not recognize. See [the model's prompt guidance](https://huggingface.co/google/embeddinggemma-300m).

## Fast local test (no Qdrant or model required)

Use the normal MVP Compose startup (`docker compose up --build`), then call:

```bash
curl -s http://localhost:8000/api/v1/policy/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Can I return a final sale item?"}'
```

The expected response has `status: "answered"`, `policy_version: "mvp-1.0.0"`, and a
`P-FINAL-SALE` citation. An unrelated question such as `What are your store opening hours?`
returns `status: "no_match"`. There is no frontend widget for this experimental endpoint; it is
available in the API docs at `/docs`.

## Optional semantic retrieval

For macOS local development, run Ollama on the host and pull `embeddinggemma`; Qdrant is private
to the Compose network and bound only to localhost on the host. Keep the normal API configuration
at lexical/extractive until indexing has completed.

```bash
ollama pull embeddinggemma
docker compose --profile rag up -d --build
docker compose exec api python -m scripts.index_policy
```

Then set `POLICY_RETRIEVER=qdrant` in `.env`, restart the API with
`docker compose --profile rag up -d --force-recreate api`, and repeat the query. The API container
uses `http://qdrant:6333` and `http://host.docker.internal:11434`; a non-Compose Python process
uses the localhost defaults in `.env.example`. To test optional LLM wording, also pull `qwen3:4b`,
set `POLICY_GENERATOR=ollama`, and recreate the API. Extractive generation is safer for factual
claims; model wording is experimental and may still be wrong despite citations. The optional
generator requests structured JSON, limits answer length, validates the cited clause IDs, and
falls back to extractive text if the result is malformed.

Indexing can be repeated. Changing the embedding model's vector dimension requires a new Qdrant
collection name (or a planned migration); do not delete a collection casually. Keep Qdrant's port
private and add authentication/TLS before any remote exposure. No real refunds, labels, or policy
decisions are performed by this route.

## Initial retrieval evaluation

`uv run python -m scripts.evaluate_policy_retrieval --backend lexical` runs 12 authored examples
against the source clause IDs, including two questions that should abstain. To evaluate an indexed
vector backend, use `--backend qdrant` with the local Ollama/Qdrant URLs configured. Report the
backend and environment alongside results; do not compare these tiny development examples with a
held-out benchmark or claim end-to-end return accuracy. The test questions were written during
development and are not an independent test set. The endpoint's answer generation and retrieval
quality should be measured separately from the deterministic case outcome.

See [local smoke-test results](results/policy-rag-local-smoke-2026-10-08.md) for the first live
Qdrant/Ollama run and its limitations.

This spike does **not** yet perform semantic fact-aware retrieval from verified order facts,
detect semantic conflict between a changed policy document and code, or validate a Jetstream2
deployment. The case-flow integration is deliberately limited to exact reason-code citations;
those larger capabilities require separate acceptance tests.
