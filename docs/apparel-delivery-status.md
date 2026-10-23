# Apparel / LLM / manual delivery implementation ledger

Base: `798ac424a5f954013e0cc5b3059e3636c0b2a0d7`; branch: `codex/apparel-llm-delivery`.

The v3 extractor namespace is frozen with its original source manifest. Existing
uncommitted evaluation reports and `data/abcd_synthetic/` are user-owned and excluded
from these checkpoints. The unapplied v4 patch and its stopped budget remain archival.

## Checkpoints

1. Expand-only schema / immutable policy / historical snapshot: in progress.
2. Owned demo accounts, LLM-first extraction, cards and durable tickets: not verified.
3. Build-once CI, pinned-image manual deployment / backup / compatible rollback: not verified.
4. Regression, real model qualification, documentation: not run.

No local Docker, no cloud changes, no main merge. Model runs, if available, are serial.
8B is the target, not a claim of qualification. Never carry Mac latency over to CPU cloud.
