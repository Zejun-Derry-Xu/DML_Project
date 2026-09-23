# ReturnFlow

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

The four MVP policies are deliberately narrow: the order must be delivered, the request must be
within 30 days, final-sale items cannot be returned, and used non-defective items are rejected.
Defects, conflicting information, unsupported cases, and explicit requests go to human review.

## Architecture

```text
React/Vite UI -> FastAPI -> Conversation service -> Rule/model extractor
                                     |-> Order service -> PostgreSQL
                                     |-> Policy engine
                                     |-> Return service -> simulated RMA
```

The local default is the deterministic rules extractor. Set `LLM_PROVIDER=ollama` to enable the
hybrid rules + Qwen path. The service calls Ollama's OpenAI-compatible API; a cloud-compatible
endpoint can be selected with `LLM_PROVIDER=openai_compatible` and the same configuration fields.

## Fastest start: Docker Compose

Requirements: Docker Desktop with Compose.

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:5173>. API docs are at <http://localhost:8000/docs>, liveness at `/health`,
readiness at `/ready`, and Prometheus metrics at `/metrics`. The compose startup applies migrations
and idempotently seeds the ten demo orders.

Demo order/email pairs include:

| Order | Email | Scenario |
|---|---|---|
| `ORD-1010` | `june@example.com` | Eligible when unused and within window |
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

