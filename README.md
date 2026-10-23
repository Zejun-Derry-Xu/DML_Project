# ReturnFlow

## Current candidate: apparel / LLM-first / manual delivery

The `codex/apparel-llm-delivery` branch replaces the product workflow with fictional
account selection, owned-order cards, LLM-first evidence extraction, natural-language
questions with deterministic answer cards, and durable simulated support tickets.
Eligibility comes from validated versioned **policy configuration**, not retrieved text
or an LLM verdict. Only apparel is automated; other categories go to support.
Old cases stay read-only. No real refunds or real authentication are implemented.

- [Current architecture and source map](docs/apparel-architecture.md)
- [Manual deployment, shutdown, backup and guarded rollback](docs/apparel-runbook.md)
- [Verification ledger and pending work](docs/apparel-delivery-status.md)

For a 16 GB Mac, start without Docker or a model:

```bash
uv sync --frozen --all-groups
cd frontend
npm ci
cd ..
make demo-guided
```

Choose a fictional account, describe a return, select an order and use the answer
cards. `Ctrl+C` stops this invocation's API/UI; its SQLite DB remains. With a separately
running Ollama and sufficient memory, `make demo` requests Qwen3 8B. The target is
**not yet qualified** on Jetstream CPU. A missing model degrades to guided cards, not
semantic keyword extraction. Do not load 8B just to demonstrate the UI on a busy Mac.

The historical sections below describe the earlier MVP/evaluation architecture.
Their 4B/rules results are not scores for the new product path. Use the current
runbook above for deployment. The runtime image no longer auto-migrates or seeds:
deployment invokes those steps explicitly before starting the image.

## Historical MVP reference

ReturnFlow is a context-aware return request agent. It combines trusted order data, persisted
conversation state, deterministic policy, and replaceable fact extractors to ask only the questions
that are still necessary. The UI and API are English-first; policy behavior depends only on stable
machine-readable fields and reason codes.

## What the MVP does

- Extracts order number, item, reason, usage, opening, damage, and human-assistance intent.
- Checks order ownership and trusted order/item attributes before asking the customer.
- Persists one structured question at a time and restores it after refresh or API restart.
- Rejects stale, expired, duplicated, cross-session, and invalid option answers.
- Makes eligibility decisions in deterministic Python code, never in an LLM.
- Creates one simulated RMA only after explicit, version-bound confirmation.
- Records messages, extraction metadata, tool latency, policy results, and stable reason codes.

Policy `mvp-2.0.0` keeps delivery, 30-day, final-sale and duplicate-return safeguards.
Catalog-classified apparel may have been worn: eligibility requires explicit no-stain/no-damage
facts and attached, intact tags. Customer-caused adverse conditions reject; arrival problems or
unresolved cause go to human review. Missing facts require questions, not assumed good condition.
Non-apparel retains the unused-item rule. This is simulated customer-reported pre-screening.
See [extraction reliability and release gates](docs/extraction-reliability-v2.md).

## Architecture

```text
React/Vite UI -> FastAPI -> Conversation service -> Rule/model extractor
                                     |-> Order service -> PostgreSQL
                                     |-> Policy engine
                                     |-> Return service -> simulated RMA
```

In the historical legacy workflow the default was the rules extractor. Set `LLM_PROVIDER=ollama` to enable the
hybrid rules + Qwen path. The Ollama adapter uses its native structured-output API so model thinking
can be disabled; a cloud-compatible endpoint can be selected with `LLM_PROVIDER=openai_compatible`
and the same configuration fields.

An experimental, read-only policy question-answering endpoint is available at
`POST /api/v1/policy/ask`. It cites clauses from a versioned simulated MVP policy. The default
lexical/extractive path needs no vector database or model; Qdrant + Ollama embeddings can be enabled
separately. It does not decide a customer's return or alter existing case decisions. See
[the policy retrieval spike](docs/policy-rag-spike.md) for setup, scope, and limitations.
Case responses also include the policy clause corresponding to a verified reason code, so the
web UI can show the basis for an existing deterministic decision without calling the vector DB.

## Low-memory local demo (no Docker)

For a 16 GB development machine, run the integrated UI/API with a separate SQLite demo DB:

```bash
uv sync --all-groups
cd frontend
npm ci
cd ..
uv run python -m scripts.local_demo --workflow legacy --provider rules --database data/local_demo/legacy.db
```

Open <http://127.0.0.1:5173>. `Ctrl+C` stops this command's API/UI; the demo DB persists.
No PostgreSQL, Qdrant, or model is started. General policy questions have a separate
**Ask policy** panel and do not modify an active return. For optional local hybrid extraction,
start Ollama separately and use `uv run python -m scripts.local_demo --provider ollama`.
See [the integration verification and development gaps](docs/integration-status.md).
SQLite is a local demonstration profile, not the production database architecture.

## Docker Compose (optional)

The following is **local development only**, not safe public-server configuration.
For the current private CPU Jetstream2 profile, use the standalone `compose.jetstream.yml` and
[current migration/start/stop/rollback runbook](docs/apparel-runbook.md). Its database/model
ports are not published; API/UI bind to loopback and are accessed through an SSH tunnel.
Do not run local Docker on a memory-constrained Mac just to test this change.

Requirements: Docker Desktop with Compose.

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:5173>. API docs are at <http://localhost:8000/docs>, liveness at `/health`,
readiness at `/ready`, and Prometheus metrics at `/metrics`. The runtime image no longer
applies migrations or seeds at startup. For legacy development invoke migrations and seed
explicitly in the API service before bringing up the frontend; prefer the isolated no-Docker
demo above. Never use this legacy Compose file on the cloud.

Demo order/email pairs include:

| Order | Email | Scenario |
|---|---|---|
| `ORD-1010` | `june@example.com` | Apparel: ask stains, attached/intact tags and damage; worn alone is allowed |
| `ORD-1005` | `emma@example.com` | Multiple items; item selection required |
| `ORD-1004` | `dev@example.com` | Final sale |
| `ORD-1003` | `cora@example.com` | Outside 30-day window |
| `ORD-1006` | `farah@example.com` | Defect goes to human review |

## Local development

Requirements: Python 3.12, `uv`, Node.js 22+, npm, and PostgreSQL 17. Ollama is optional.

```bash
cp .env.example .env
uv sync --all-groups
uv run alembic upgrade head
uv run python -m scripts.seed_data
uv run uvicorn app.main:app --reload
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

To use local Qwen, install Ollama separately, pull `qwen3:4b`, start Ollama on port 11434, then set:

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:4b
LLM_BASE_URL=http://localhost:11434/v1
```

When the API runs inside Compose, the default model URL is
`http://host.docker.internal:11434/v1`, preserving Apple Silicon/Metal acceleration on macOS.

## Quality checks

```bash
make check
docker compose build
```

The backend suite covers policy boundaries, missing-field priority, structured answers, stale and
duplicate protection, identity checks, multi-item selection, fact conflicts, and natural-language
conversations. The labeled extraction set contains 50 held-out phrases. CI uses rules/fake parsing
and never downloads a model.

Measured outputs are checked in under `docs/results/`. On the 50-case set, the rules baseline reached
100% labeled-slot accuracy; local Qwen3:4B reached 56.16%. These are partial-label, offline results,
not production claims, and they support keeping deterministic rules as the primary path.

## Public-data evaluation experiment

The experimental public-data evaluators run without Docker or the application database.
They cover ABCD fact extraction, OR-ShARC retrieval/rule reading, a separate retail-policy
boundary supplement, and an isolated official tau2 compatibility runner. See
[the measured results and reproduction guide](docs/public-data-evaluation.md).
Full retrieval results, small local-model samples, and authored tests are reported separately;
none is presented as a complete native ReturnFlow end-to-end benchmark score.

## API flow

1. `POST /api/v1/chat` with `session_id`, `customer_email`, and a free-text `message`.
2. Render the returned `question` options, if present.
3. Submit a button answer to `POST /api/v1/questions/{question_id}/answer`, or submit equivalent
   free text to `/chat`.
4. For an eligible case, answer the server-generated `confirm_return` question.
5. Store the returned simulated RMA reference. Repeating the confirmation does not create a second
   request.

See [docs/api.md](docs/api.md) for request examples and [docs/architecture.md](docs/architecture.md)
for trust boundaries and state progression.

## Repository layout

```text
app/          FastAPI API, domain, extractors, services, repositories, database, observability
frontend/     React/Vite TypeScript chat UI
migrations/   Alembic migrations
data/         Deterministic ten-order seed definition
tests/        Unit, integration, natural-language, and evaluation fixtures
scripts/      Seed and evaluation commands
docs/         Architecture, API, decisions, and experiment artifacts
```

## Privacy and safety

Logs contain request/session metadata and latency, but not raw messages, complete emails, secrets,
or model credentials. The database stores messages for the auditable demo flow. Do not put API keys
in the repository. No endpoint performs a real refund, payment action, or shipping-label creation.
