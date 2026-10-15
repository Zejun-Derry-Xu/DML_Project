# Private Jetstream2 v2 deployment — release-gated runbook

This is a NEW standalone Compose file, not an override. No cloud deployment was
performed by this change. Do not deploy until the reliability report and human
label audit gates are satisfied. Use only CPU; no GPU, no public model/database ports.

## Preserve the existing deployment first

Keep the instance Shelved until local validation is complete. Unshelve, check its
current public IP, SSH as exouser. Keep the existing `.env` and database password:
changing POSTGRES_PASSWORD does not rotate credentials inside an existing volume.
Do not print `docker compose config` without `--quiet` or share `.env`.

Before changing code, record `git rev-parse HEAD`, `git status --short`,
`docker compose ps`, and `docker inspect returnflow-ollama --format '{{.Image}}'`.
Record `docker image inspect ollama/ollama --format '{{index .RepoDigests 0}}'` and
set OLLAMA_IMAGE to that exact tested digest in the server `.env`.
Keep LLM_PROVIDER=rules during the migration. Do not copy `.env.jetstream.example`
over an existing secret file. Retain old Compose edits/backups outside Git.

Verify volume identities before migration:

```bash
docker volume inspect returnflow_returnflow-db returnflow-ollama
docker inspect returnflow-db-1 --format '{{json .Mounts}}'
docker inspect returnflow-ollama --format '{{json .Mounts}}'
```

The new file explicitly reuses these volume names. Stop if names differ; never
assume a new empty volume is a successful migration. Stop API writes before backup:

```bash
cd ~/returnflow
docker compose stop api frontend
umask 077
mkdir -p backups
docker compose exec -T db pg_dump -U returnflow -d returnflow -Fc > backups/pre-v2.dump
test -s backups/pre-v2.dump
docker compose exec -T db pg_restore --list < backups/pre-v2.dump
```

The archive is sensitive and ignored by Git/Docker. A list check is NOT a restore
test: restore into an isolated temporary PostgreSQL database, check row counts,
then run readiness and workflow smoke against the restored copy before approving
the restore gate. Never restore over the live database to "test" a backup.

## Switch code and Compose deliberately

Fetch `codex/extraction-reliability-v2` and check out the tested commit after reviewing
local changes; do not use reset --hard. v2 adds nullable columns and explicit seed
catalog categories. Completed cases keep their original policy version. Resuming
an unfinished v1 case invalidates its old confirmation and re-evaluates v2 conditions.

Stop the separately managed model container before sharing its weight volume:

```bash
docker stop returnflow-ollama
docker compose -f compose.jetstream.yml config --quiet
docker compose -f compose.jetstream.yml up -d --build db api frontend
curl -fsS http://127.0.0.1:8000/ready
docker compose -f compose.jetstream.yml --profile model up -d ollama
docker compose -f compose.jetstream.yml exec ollama ollama list
```

If the model is absent, explicitly pull `qwen3:4b` with Compose exec. Record the
model manifest digest and Ollama version; tags alone do not pin model weights.
Set LLM_PROVIDER=ollama in `.env` only after rules-mode migration smoke, then:

```bash
docker compose -f compose.jetstream.yml up -d --no-deps api
curl -fsS http://127.0.0.1:8000/ready
```

API DNS is now `http://ollama:11434/v1`; do not rely on host.docker.internal or a
manually connected container. All services share the Compose network. Ollama has
no published port, one parallel request, 6 CPU / 10 GiB limits. These are limits,
not guaranteed performance or a substitute for application admission control.

On the Mac, open an SSH tunnel using the CURRENT server IP:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 15173:127.0.0.1:5173 exouser@CURRENT_PUBLIC_IP
```

Visit http://localhost:15173. Test 20 serial extraction requests, cold/warm timing,
multi-turn clothing conditions, arrival defects, missing conditions, cancellation,
explicit confirmation, reload recovery and duplicate protection. Inspect actual
fact_extractor traces for model failures, rejected evidence, tokens and latency;
`/health` or correct configuration alone is not proof of model use or quality.
No production authentication/TLS or physical product inspection is claimed.

Use an isolated test database/order set for state-changing smoke. If ORD-1010 was
already returned in the old deployment, duplicate rejection is correct. Seeding
does not reset its return status or delivery date. Do not delete historical RMAs
or reset the live database just to obtain a passing demo.

## Daily operation and rollback

```bash
# Start (after Unshelve and SSH)
docker compose -f compose.jetstream.yml --profile model up -d db api frontend ollama
# Inspect; logs can contain customer data: do not publish them
docker compose -f compose.jetstream.yml ps
# Stop before Shelve; Ctrl+C on the Mac closes the separate SSH tunnel
docker compose -f compose.jetstream.yml --profile model stop
```

Then select Shelve, NOT Delete, in Exosphere. Never run `down -v`.

Quality rollback: set LLM_PROVIDER=rules and recreate only API; keep v2 policy and
unknown-fact questions. Do NOT silently return to v1 apparel approval logic.
Schema rollback is intentionally disabled. For code rollback, stop writes and
select a schema-compatible tested commit. Returning to v1 requires an explicit
policy decision; restoring a pre-v2 backup can discard subsequent returns and
requires explicit approval and reconciliation. No automated data-loss rollback.
