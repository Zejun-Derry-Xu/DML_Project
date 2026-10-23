# Apparel / LLM / manual delivery implementation ledger

Base: `798ac424a5f954013e0cc5b3059e3636c0b2a0d7`; branch: `codex/apparel-llm-delivery`.

The v3 extractor namespace is frozen with its original source manifest. Existing
uncommitted evaluation reports and `data/abcd_synthetic/` are user-owned and excluded
from these checkpoints. The unapplied v4 patch and its stopped budget remain archival.

## Checkpoints

1. Expand-only schema / immutable policy / historical snapshot: committed `378021c`, pushed.
2. Owned demo accounts, LLM-first extraction, cards and durable tickets: committed `7db7fea`, pushed.
3. Build-once CI, pinned-image manual deployment / backup / compatible rollback: committed
   `3ad1930`, pushed. That commit's GitHub PostgreSQL and real image smoke passed.
4. Local regression, browser verification, guarded rollback checker and documentation:
   committed `cd7c5e8`, pushed and CI passed; final checkpoint evidence below. Real model
   qualification and live cloud adoption are deliberately NOT completed.

No local Docker, no cloud changes, no main merge. Model runs, if available, are serial.
8B is the target, not a claim of qualification. Never carry Mac latency over to CPU cloud.

## Local evidence (2026-10-23)

- 313 pytest tests passed (272 historical + 41 new); Ruff and strict application mypy passed.
- Frontend lint/build passed.
- A fresh SQLite database migrated through 0001–0004; `alembic check` detected no drift.
- A real loopback HTTP server passed read probes, schema checks, policy citation
  and the guided account/order/cards/confirmation/RMA flow (4 smoke groups).
- Semantic fakes test transitions, not Qwen accuracy. No local Docker was started.
- No 8B load or sampling was attempted on this memory-constrained Mac. The model is
  NOT qualified. Cloud CPU/model qualification and live deployment are pending.
- Latest local HTTP run used a fresh temporary SQLite DB, migrated 0001–0004,
  checked no schema drift, and passed all 4 smoke groups. Model transport was NOT exercised.
- Browser: Bob saw only his own DEMO-2001 order; entered a raw reason; answered stains
  "I'm not sure", then damage/tags questions; got one simulated support ticket, not
  an RMA. Refresh and account reselection restored the same ticket. Reported false
  and unknown facts and policy clauses display readable language, not internal JSON.
- Rollback tests cover pair-bound evidence, downgrade-flag bypass, backup and smoke
  failures, retained stopped test projects, and isolated cleanup. These use subprocess
  fakes: no real two-version Docker rollback run has occurred locally.

## Remote evidence and deployment boundary

- [CI for 3ad1930](https://github.com/Zejun-Derry-Xu/DML_Project/actions/runs/40002428153):
  completed successfully, including real PostgreSQL API tests and Linux container smoke.
- [Final implementation CI for cd7c5e8](https://github.com/Zejun-Derry-Xu/DML_Project/actions/runs/40015198640):
  completed successfully on 2026-10-23. Backend, frontend and container jobs all passed,
  including the new operator-bundle input check. This evidence refers to that exact
  implementation commit, not an untested successor or an actual cloud deployment.
- No publication on this experimental branch. Main-only GHCR push/artifact publication,
  first real image-pair rollback exercise, existing-volume adoption, restore rehearsal
  and 8B CPU validation remain explicit follow-ups when the owner opens Jetstream2.
- No merge into main; no local Docker; no Jetstream2 changes or wake-up.

## Operator documents

- `docs/apparel-runbook.md`: first adoption, normal start/stop, manual promotion,
  stage-specific failure handling, backup verification and rollback qualification.
- `docs/apparel-architecture.md`: high-level interaction, container boundaries and source map.
- `README.md`: distinguishes current LLM-first candidate and safe no-model local demo
  from legacy rule-first evaluations. Historical scores are not new-model scores.
