# Apparel / LLM / manual delivery implementation ledger

Base: `798ac424a5f954013e0cc5b3059e3636c0b2a0d7`; branch: `codex/apparel-llm-delivery`.

The v3 extractor namespace is frozen with its original source manifest. Existing
uncommitted evaluation reports and `data/abcd_synthetic/` are user-owned and excluded
from these checkpoints. The unapplied v4 patch and its stopped budget remain archival.

## Checkpoints

1. Expand-only schema / immutable policy / historical snapshot: committed `378021c`, pushed.
2. Owned demo accounts, LLM-first extraction, cards and durable tickets: implemented.
3. Build-once CI, pinned-image manual deployment / backup / compatible rollback: not verified.
4. Regression, real model qualification, documentation: not run.

No local Docker, no cloud changes, no main merge. Model runs, if available, are serial.
8B is the target, not a claim of qualification. Never carry Mac latency over to CPU cloud.

## Local evidence (2026-10-23)

- 297 pytest tests passed (272 historical + 25 new); Ruff and strict application mypy passed.
- Frontend lint/build passed.
- A fresh SQLite database migrated through 0001–0004; `alembic check` detected no drift.
- A real loopback HTTP server passed read probes, schema checks, policy citation
  and the guided account/order/cards/confirmation/RMA flow (4 smoke groups).
- Semantic fakes test transitions, not Qwen accuracy. No local Docker was started.
- Ollama is not running; the Mac already has substantial compressed memory. 8B has
  NOT been loaded, sampled, or qualified. Cloud CPU/PG/container acceptance is pending.
