# Checklist deployment preparation — 2026-10-25

Status: **deployed as an owner-approved unqualified course demo**. Infrastructure
and fallback checks pass; real natural-language one-step submission timed out and
FAILED acceptance. The midpoint report has not been changed. No main merge,
local Docker, volume deletion or live data restore.

## Candidate and checks

- Application commit: `534db39ea2496e9c320b1c2391dee9d45c5f405e`.
- Installed release: `da62fb3c311719dc8063284f4c8420cd60c2ec61`.
- Branch: `codex/extraction-harness-v1`.
- Installed candidate tag: `returnflow-candidate-checklist-20261025-pinned`.
- Follow-up defaults the operator model to Qwen3 4B and adds the checklist HTTP
  suite to the dedicated PostgreSQL CI step. It does not enable LLM mode by default.
- Local working-tree checks: Ruff, mypy (86 sources), 471 backend tests, six
  frontend tests, ESLint and TypeScript/Vite build passed. Some evaluation files
  remain uncommitted; the local count is not the clean release CI test count.
- Installed candidate CI: https://github.com/Zejun-Derry-Xu/DML_Project/actions/runs/40206687725
  succeeded: 399 clean-checkout tests, 54 dedicated PostgreSQL integration tests,
  frontend checks and tested image HTTP smoke. These are not a real Qwen quality score.
- Downloaded release artifact checksum verified locally. Cloud operator-script SHA-256
  matched that artifact: `6a729b45eb58be0734c43aac6a037ef78150ee59a19f8099536732401f45e499`.

## Verified cloud state

Instance `c5abd2b7-4370-43ff-bc21-8d40cd512611`, IU, `returnflow`, public IP
`149.165.169.223`, internal IP `10.1.82.60`. Verified through the logged-in instance
page and Web Shell, not by trusting a historical IP.

Before the switch, the running app was commit `847c7b31785f69afc1b440df6d211b0cceee5848`,
`EXTRACTION_MODE=guided`, schema `0004`, policy `apparel-1.0.0`.
with three app containers and no running Ollama. The old model name in `/ready`
was configuration, not evidence of inference.

Frontend is bound to `0.0.0.0:5173`, API to `127.0.0.1:8000`; PostgreSQL has no
published host port. Existing application volumes are `returnflow_returnflow-db`
and `returnflow-ollama`; neither was deleted or renamed.

## Backup and restore rehearsal

Private cloud backup directory:
`/home/exouser/returnflow-candidate-847c7b3/backups/pre-checklist-20261025.96CVKd`.
Contains a PostgreSQL custom-format dump, readable archive listing, and private
copies of the existing operator environment and release records. Do not upload
these private files to GitHub or print their contents.

The existing `scripts.verify_backup` restored this dump into a NEW database:
`returnflow_checklist_20261025_1510_restore_test`.
It succeeded and queried six cases and one return request. The live database was
not overwritten. The isolated test copy is intentionally retained; no cleanup or
data deletion was performed. This verifies this backup's restore path, not every
disaster-recovery scenario or a new application's rollback compatibility.

## Blocking release decision

`scripts/deploy_release.py` requires a reviewed, matching CPU qualification report
before promoting LLM mode. No report for this candidate and Qwen3 4B has been
verified. Historical 4B protocol diagnostics showed unsupported fills; passing
unit tests or successful HTTP inference is not a semantic qualification.

Do not forge a qualification file, disable the gate, silently deploy guided mode
as the requested 4B experience, or describe the latest candidate as live.
Recommended next step: isolated cloud candidate with a separate synthetic database,
then real Qwen/checklist acceptance while retaining the old public deployment.
The owner subsequently explicitly chose direct deployment despite that limitation.
An exact-commit course-demo exception was added, with tests; it is not a fake
qualification report. Default reviewed qualification remains enforced. The exception
requires the synthetic Jetstream environment, records its unqualified status and
cannot authorize rollback.

Release preparation caught a separate legacy bug: the manifest generator hardcoded
8B although this candidate config selects 4B. That manifest was NOT installed.
The generator now defaults to 4B, and deployment rejects mismatched manifest/operator
model names. The old qualification-gate test needed its matching-model fixture
updated; its missing-qualification rejection assertion remains unchanged.

The cloud runtime is started privately, with the existing model volume, six CPU cores
and a 12 GiB limit; both 4B and 8B weight files exist, but only 4B is selected for
this release. An independent `returnflow-checklist-acceptance-db` was created for
synthetic write acceptance, with no published ports; no live orders were reset.
## Actual switch and public checks

Installed operator directory: `/home/exouser/returnflow-checklist-da62fb3`.
The original deployment directory and its previous image pair remain intact.
The deployment script made another write-paused database backup,
`backups/20261025T153735527071Z.dump`, applied the additive migration check,
switched the tested image pair, checked the pinned model digest, and passed three
read-only HTTP checks. It wrote `.current-release.json` only after those checks.

- API image: `ghcr.io/zejun-derry-xu/dml_project-api@sha256:ed48201c26c4b3d16b6c271ebb4c3c3cff55536f0dc9576963a98c332e47964b`.
- Frontend: `ghcr.io/zejun-derry-xu/dml_project-frontend@sha256:9310b61e4d562d3db6d1e56f783be431504492c64152fc00e9c5a27b74a72fbc`.
- Qwen3 4B: `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
- Public entry: https://http-149-165-169-223-5173.proxy-js2-iu.exosphere.app/
- Public `/ready` and `/version.json` both returned the installed commit above;
  `/ready` reported `llm`, `checklist`, `qwen3:4b`, schema `0004`.
- Browser checks passed for page rendering, secure demo-account selection, chat
  intake, owned-order selection, all four checklist conditions and policy lookup
  with the `A-WINDOW` citation. No live return was submitted in the browser.
- Four app containers are running: frontend, API, PostgreSQL and Ollama. Ollama
  has no published host port, and was observed using about 3.43 GiB of its 12 GiB
  limit; API about 73 MiB of its 1 GiB limit. These are snapshots, not load-test results.

A temporary GHCR DNS error during the first frontend pull resolved on retry; no
resolver/firewall changes were made. A transient 502 was observed while old
API/frontend containers were intentionally stopped; the final public checks passed.

## Real CPU acceptance: mixed results, NOT all passed

The identical API digest ran against a separate synthetic PostgreSQL database and
the real private Ollama service. No fake model responses were used.

**Failed:** after intake and a valid checklist, the request
`None of these problems apply, and submit my return.` returned after **60.04 s**
as `awaiting_user`, `degraded=true`, with no RMA. The assertion requiring
`return_created` failed; natural-language idempotency checks after that assertion
were NOT executed. Do not count them as passed.

The actual model logs showed prompt processing around 48 tokens/s, generation
around 4–5 tokens/s and cancellation at the 60 s request deadline. The preceding
order-selection/replayed-intake request took about 51.2 s. This is real CPU latency,
not proof that a generic accuracy benchmark is good or bad. No timeout increase,
prompt rewrite, model change or hardware change was made to hide the failure.

**Passed on the failed request's retained case:** explicit checklist button created
one simulated RMA; repeating the same answer returned the same RMA; GET refresh
recovered it. These are button-fallback results, not natural-language success.
Separate cases rejected an expired order (`OUTSIDE_RETURN_WINDOW`) and final-sale
order (`FINAL_SALE`). Bob could not read Alice's case (404).

The isolated acceptance API and DB are stopped after testing, not deleted. Their
synthetic records and the isolated restore-test database are retained. The public
application's original demo orders were not reset or overwritten.

The deployment is available with a working explicit fallback, but the intended
one-sentence happy path is not yet accepted on this CPU host. Do not mark all tests
green, imply formal model qualification, or update the midpoint report with such
a claim. Any later report update must state this limitation or follow a separately
verified latency fix.
