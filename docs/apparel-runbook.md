# Apparel delivery operator runbook

Status: candidate `847c7b3` was deployed to Jetstream2 in guided mode. Newer source
and experimental model trials are not automatically the installed release.
This supersedes `jetstream-v2-runbook.md` for the new apparel workflow only.
Do not run these cloud commands until the owner opens the VM and approves deployment.

## 1. What is being delivered

Three always-on services: frontend (Nginx), API (FastAPI), database (PostgreSQL).
A fourth service, Ollama, is optional and only starts with the `model` profile.
The default deployment is **guided**: users answer condition cards, and unresolved
facts produce a simulated support ticket. It is not a successful LLM qualification.
There is no Qdrant requirement for the default lexical/extractive policy path.

The fictional account picker is NOT real authentication. Only synthetic data may be
loaded. No payment, actual refund, email notification or external ticket integration exists.
The default service is loopback-only and accessed through SSH. An explicitly approved
synthetic course demo can expose only its Nginx entry point as described below;
this is not a public production storefront.

### Explicit unqualified course-demo exception

The normal LLM path still requires matching reviewed CPU qualification. If the owner
explicitly chooses an unqualified **synthetic** demo despite known extraction errors,
the operator may pass `--unqualified-demo-commit EXACT_40_HEX_RELEASE_COMMIT` and
`--unqualified-demo-model-digest EXACT_64_HEX_INSTALLED_MODEL_DIGEST` to the
deployment script. This is not model qualification: the deploy log and installed
release mark `unqualified_owner_approved_course_demo`. The option requires
`ENVIRONMENT=jetstream-demo` and `DEMO_ENABLED=true`, matches only that release, and
cannot authorize rollback. It retains pinned runtime/images, backup, migration,
paired-version checks and HTTP smoke. Never use it for real customer data or claim
that model accuracy passed. Each future release needs a fresh explicit owner choice.

## 2. Release and approval

1. Work on an experimental branch. PR/push CI runs backend checks, a real PostgreSQL
   workflow test, frontend checks, and actual Linux image HTTP smoke.
2. An approved merge/push to `main` publishes the SAME tested API/frontend images
   to GHCR. A separately approved candidate can instead be released with a manually
   created `returnflow-candidate-*` tag, without merging main. Ordinary experimental
   branch pushes never publish. Manual workflow dispatch on `codex/apparel-llm-delivery`
   also requires the explicit `publish_candidate=true` input. Every release path runs
   the full checks and image smoke before publication; none deploys to the VM.
3. Download `returnflow-release-<commit>` from that CI run. It contains the operator
   bundle, checksum and `release.json` binding both image digests, commit, CI sequence,
   migration head and policy checksum. CI does NOT log into the VM or deploy.
4. A person checks the CI result, manifest and intended extraction mode, then runs the
   deployment script on the VM. This is continuous delivery with a manual promotion
   gate, not automatic continuous deployment.

Candidate publication/GHCR permissions and the download path require their own
verified run. A successful ordinary branch CI does not prove publication works.
Keep the artifact checksum from the trusted GitHub run: a checksum bundled alongside
an untrusted download is not an independent authenticity signature.

## 3. Before touching the existing VM

- Confirm host identity, current allocation, disk/RAM and the actual current IP.
- Inventory running containers, networks, volume names, migration head and existing
  `.env`; do not assume the 2026-10-15 manual installation matches this candidate.
- The deployment file preserves `returnflow_returnflow-db` and `returnflow-ollama`.
  Verify they really are the intended volumes before using this file.
- Existing DB password must remain the CURRENT volume password. Changing `.env`
  alone does not rotate a PostgreSQL password stored in an existing volume.
- Preserve old Compose files/config and take a database backup before first adoption.
  Old manual releases have no compatible-pair evidence: do not invent it.
- Use a separate operator directory for the downloaded bundle; preserve private `.env`
  and manifest files across upgrades. Do not unpack a new bundle over private state.

Private `.env` is based on `.env.jetstream.example`. Generate secrets locally/on the
server, never paste them into chat, commit them or print Compose's resolved config.
Use hex-only DB passwords to avoid URL-encoding errors in `DATABASE_URL`.
Set `chmod 600 .env`. For SSH-tunnel HTTP use `DEMO_COOKIE_SECURE=false`; set it true
only after serving through HTTPS. The default is `EXTRACTION_MODE=guided`.

## 4. First deployment (VM, explicitly approved only)

From the verified, extracted operator bundle directory, with its private `.env`:

```bash
sha256sum -c returnflow-release.sha256 # run beside the downloaded archive before extraction
bash scripts/deploy.sh release.json --initialize --seed-demo
```

The checksum command belongs in the download directory. The deploy command belongs
inside the extracted bundle. `--seed-demo` is for a synthetic demo DB only; it creates
fictional accounts idempotently, never converts real customers into demo customers.

The script locks concurrent deployment, validates immutable digests, pulls both
images before stopping anything, verifies OCI commit labels, stops API/UI writes,
backs up PostgreSQL, checks the archive listing, applies expand-only migrations,
optionally seeds, starts the pair, verifies frontend/API/schema/policy identity,
and performs a read-only HTTP smoke. It never rebuilds an image on the VM.

`pg_restore --list` checks archive readability, not full recovery. Test recovery separately:

```bash
python3 -m scripts.verify_backup backups/EXACT_BACKUP_FILENAME.dump \
  --database returnflow_unique_trial_restore_test
```

Replace the filename and choose a NEW database name. This command refuses existing
databases and intentionally leaves the test copy. It does not restore over live data.
There is no automatic live restore in this project; real recovery needs an explicit
data-preservation decision, rehearsal and maintenance window.

## 5. Every start / stop

After a successful deployment generated `.release.env`:

```bash
docker compose --env-file .env --env-file .release.env -f compose.jetstream.yml up -d --no-build --wait db api frontend
curl --fail http://127.0.0.1:8000/ready
curl --fail http://127.0.0.1:5173/version.json
docker compose --env-file .env --env-file .release.env -f compose.jetstream.yml exec -T api python -m scripts.smoke_apparel
```

For an already qualified LLM installation, include `--profile model` before `up`
and add `ollama` to the service names. Starting Ollama does not download the model.

### Hosted Qwen Flash instead of Ollama

Do not start the `model` profile when `LLM_PROVIDER=dashscope`. In the VM private
`.env` (mode `600`, never committed), set:

```env
LLM_PROVIDER=dashscope
DASHSCOPE_API_KEY=<key created in the same region as the base URL>
LLM_MODEL=qwen3.7-flash
LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
DASHSCOPE_RESPONSE_FORMAT=auto
```

The API container receives `DASHSCOPE_API_KEY` from that file. The frontend image
does not. If `LLM_MODEL` is left as `qwen3:4b` or `qwen3:8b`, the API calls
`qwen3.7-flash`. If `LLM_BASE_URL` is left as the Ollama address, the API uses the
Singapore compatible-mode URL above. Override the base URL for a workspace domain
or for US (Virginia): `https://dashscope-us.aliyuncs.com/compatible-mode/v1` or
`https://{WorkspaceId}.us-east-1.maas.aliyuncs.com/compatible-mode/v1`. Keys do not
work across regions. Return to CPU Ollama with `LLM_PROVIDER=ollama`,
`LLM_MODEL=qwen3:4b`, `LLM_BASE_URL=http://ollama:11434/v1`, and `--profile model`.
`/model/status` lists the hosted model and still reports `inference_tested: false`.

On the Mac (replace `CURRENT_HOST` with the verified current IP or working DNS):

```bash
ssh -N -L 15173:127.0.0.1:5173 -L 18000:127.0.0.1:8000 exouser@CURRENT_HOST
```

Open `http://127.0.0.1:15173`. Closing that tunnel stops access, not server containers.

### Optional instructor-facing synthetic demo

Only after explicit approval, use the configurable UI binding in
`compose.jetstream.yml` and set `FRONTEND_BIND_ADDRESS=0.0.0.0` in the server's
private `.env`. Keep the API binding at `127.0.0.1:8000`; do not publish database
or model ports. Preserve private `.env` and Compose backups before changing them.
Recreate only Nginx, using the already tested image:

```bash
docker compose --env-file .env --env-file .release.env -f compose.jetstream.yml config --quiet
docker compose --env-file .env --env-file .release.env -f compose.jetstream.yml up -d --no-deps --no-build --wait frontend
```

Check the HTTPS platform-proxy URL from outside the VM. For the public IP observed
on 2026-10-24, the verified entry is:

<https://http-149-165-174-228-5173.proxy-js2-iu.exosphere.app/>

The raw `http://CURRENT_PUBLIC_IP:5173/` origin serves HTML, but is **not** the
supported interactive link: the current frontend uses `crypto.randomUUID`, which
requires a secure browser context. Localhost previously masked that constraint.
Use the verified HTTPS entry rather than disabling browser security or injecting
a runtime polyfill into a tested image. TLS terminates at the platform proxy;
the hop from that proxy to the VM is HTTP, not end-to-end TLS.

Check HTML, API calls through Nginx, the version, and a synthetic input/output
interaction in a fresh browser context without an SSH tunnel. Check the
actual Docker bindings too: `8000` remains loopback, and PostgreSQL/Ollama have no
published host ports. If cloud security rules need changing, allow only the app's
TCP `5173` entry for the intended audience; never disable the firewall or open
all ports as a shortcut.

The origin remains HTTP with fictional accounts and is not suitable for real customer
information, passwords or payments. A public demo permits visitors to select demo
accounts and modify their simulated cases; the selector is not access control.
The demo's HTTPS proxy alone is not production security: a real service also needs
real authentication and protection of the origin connection. Never put `.env` in Git.

To make the demo private again, set `FRONTEND_BIND_ADDRESS=127.0.0.1` in `.env` and
run the same frontend-only command, then verify the public URL is no longer reachable.
Shelving stops access; unshelving may change the public IP. Recheck and update the
report URL before class. Do not run migrations, reset cases or enable a model merely
to change this network binding.

To stop this application's containers without deleting volumes:

```bash
docker compose --env-file .env --env-file .release.env -f compose.jetstream.yml --profile model stop
```

Then the owner can shelve the VM. Never use `down -v`, volume prune, migration downgrade,
or blind database restoration as a shutdown/rollback shortcut.

## 6. Failure and rollback

| Stage | Meaning | Response |
|---|---|---|
| 2 | configuration, qualification, pull or precondition failed | No image switch; inspect private config and current services |
| 3 | backup/migration/seed failed | API/UI may be stopped; preserve backup and inspect before restarting |
| 4 | switch/readiness/smoke failed | Pending images may be running; preserve pending/previous manifests and DB |

`deploy.log` records stage/commit, not secrets. `.current-release.json` is updated only
after checks pass. `.pending-release.json` is a diagnostic marker, not proof of success.
The script does not automatically restore a backup or roll the DB back after failure.

Before granting rollback permission, run the compatibility checker on a disposable
Linux/Docker test host, NOT this 16 GB Mac or live DB:

```bash
python3 -m scripts.check_rollback --current release.json --previous previous-release.json \
  --approved-manifest approved-release.json
```

It creates a uniquely named isolated PostgreSQL project, migrates with the current
image, creates a completed simulated return and a future-workflow record, switches
to the previous pair, and checks data readability and unknown-workflow read-only
behavior. No live volumes are attached. Its output binds exact API AND frontend
digests; merely listing an old commit is insufficient. Retained stopped test containers
block reuse, and cleanup removes only that test project's containers (not volumes).

Use the approved manifest for the NEW deployment so `.current-release.json` carries
the evidence. Only then is this manual rollback allowed:

```bash
bash scripts/deploy.sh previous-release.json --rollback
```

The DB stays at the expanded schema and receives another backup. New business rows
are retained. An old release must be tested compatible; lack of a tested prior image
pair is a blocker, not permission to bypass the gate. The checker itself has unit
coverage locally; a real two-release Docker compatibility run is still pending.

## 7. Qwen qualification is a separate, blocking step

Qwen3 8B is a CPU target, not an available or qualified model claim. Ollama is limited
to one loaded model, single parallel request, 4096 context and 512 output tokens;
the adapter has a 60-second total budget. There is no GPU configuration.

Use an isolated CPU staging setup with the SAME API image, policy, Ollama image digest
and model digest, a disposable DB, and `ENVIRONMENT=ci-smoke`. Do not first enable the
live `llm` deployment to get a report: the deploy gate correctly blocks that circular
path. Staging qualification provisioning is a manual follow-up when the VM is open.

`scripts/qualify_apparel_model.py` provides serial/resumable calibration (three
temperatures, two seeds) and validation (24 diagnostic + 180 regression examples),
sharing a 90-minute model-call budget. Output goes under ignored `data/evaluation_runs/`.
It checks dataset/source/model identities before resuming. Automatic labels stay
provisional; human review of every scored validation ID is required. `false` is scored.
The final gate also needs real-model application smoke, observed memory peak below
12 GiB, warm P95 at most 30 seconds, CPU-only proof, >=90% known-field macro accuracy,
zero extraction errors and zero unsupported fills on reviewed absence labels.
This is not proof of all business safety or public-benchmark quality.

The write smoke is permitted only on loopback with a disposable `local-demo`/`ci-smoke`
DB, never `jetstream-demo`. Resetting a smoke's returned demo item is not automatic;
use a fresh disposable DB instead. The production deployment smoke is read-only.
If qualification fails, keep guided mode; a 4B fallback is an explicit separate
configuration/qualification decision, never an automatic silent downgrade.

## 8. Remaining limitations

- No real identity provider, physical inspection, shipping, refunds, email or staffed tickets.
- Lexical policy QA can abstain on broad/paraphrased questions; citations do not prove retrieval quality.
- Single VM, no replicas/load balancing/automatic failover; updates cause planned downtime.
- Resource caps are protective starting limits, not demonstrated CPU throughput guarantees.
- Backups are local to the VM: off-host retention and live recovery rehearsal remain follow-up work.
- Logs/metrics exist, but no alert delivery or complete distributed tracing dashboard.
- Manual approval means a human runs the promotion script; no GitHub Environment approval/SSH CD yet.
