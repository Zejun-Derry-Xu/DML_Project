# Official tau2 retail interactions on local Ollama

This harness runs the official retail environment, tools, policy, user simulator,
`LLMAgent`, orchestrator, and `EvaluationType.ALL` scorer from
[sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench/tree/dd8757d4c8791dad7b3cdaf02a105a3d5f9d86bd),
pinned to `dd8757d4c8791dad7b3cdaf02a105a3d5f9d86bd` (tau2 1.0.1).
Both conversation participants use locally installed Ollama models. This is an
official-agent baseline on the public benchmark. It does **not** establish the
end-to-end performance of the ReturnFlow application: ABCD extraction and
OR-ShARC retrieval/reasoning measure the application components separately.

The pinned retail splits contain 74 train tasks, 40 test tasks, and 114 base
tasks. `--split all` also includes all 114; the runner reads the upstream split
file rather than assuming that a split name always covers the whole corpus.
Forty tasks contain nonempty natural-language assertions used in their reward
basis. These are recorded as `excluded_nl_assertions`, without calling an external
judge. The other 74 are eligible for official deterministic scoring. A
`NL_ASSERTION` reward-basis label with null/empty assertions is eligible because
the official scorer returns 1 for that component without an LLM call.

## Separate official runtime

The production `pyproject.toml` needs no tau2 dependencies. One command creates
an ignored checkout and its isolated environment, without running a model:

```bash
uv run python scripts/setup_tau2_eval.py
```

The helper requires Git and uv, pins the exact source revision, installs only
the upstream locked base dependencies plus `websockets==15.0.1`, and verifies
the package imports. It rejects an existing checkout at another revision or
with local changes. `--source /path/to/new/checkout` overrides its destination.
The equivalent individual commands are:

```bash
git clone https://github.com/sierra-research/tau2-bench.git data/evaluation_sources/tau2/source
git -C data/evaluation_sources/tau2/source checkout dd8757d4c8791dad7b3cdaf02a105a3d5f9d86bd
uv sync --project data/evaluation_sources/tau2/source --locked --no-dev
uv pip install --python data/evaluation_sources/tau2/source/.venv/bin/python websockets==15.0.1
```

At this revision, text-mode imports reach the OpenAI voice provider and require
`websockets`, although the upstream base dependencies omit it. The last command
addresses that import in the isolated environment; no voice service is used.
The upstream lock pins LiteLLM 1.81.11. Python must be 3.12 or 3.13.

The source's `data/` is used by default. An explicit `--data-dir` must contain
`tau2/domains/retail/{tasks.json,db.json,policy.md,split_tasks.json}`. The runner
checks the source commit, rejects modifications to source/policy/tools/scorer,
and verifies each runtime retail file byte-for-byte against the pinned Git
revision. Flat downloaded files in `data/evaluation_sources/tau2/` are a provenance
copy, not automatically an executable official data root.

## Bounded smoke and full requests

Start Ollama with `qwen3:4b` installed, then run a task selected before inspecting
its outcomes. Task 48 belongs to train and requests a return plus a follow-up
eligibility question. The scenario is supplied only to the user simulator; the
agent receives public policy, tool schemas, and conversation/tool results.

```bash
uv run python scripts/evaluate_tau2.py \
  --task-ids 48 --split train --num-tasks 1 --seeds 300 \
  --max-steps 20 --num-ctx 8192 \
  --task-timeout-seconds 180 --call-timeout-seconds 60 \
  --total-timeout-seconds 180 --output-dir data/evaluation_runs/tau2/my-smoke
```

For a full public request with one seed:

```bash
uv run python scripts/evaluate_tau2.py \
  --split all --num-tasks 0 --seeds 300 --max-steps 100 \
  --task-timeout-seconds 600 --call-timeout-seconds 120 \
  --output-dir data/evaluation_runs/tau2/my-all
```

Forty judge-dependent rows remain explicitly unscored in that full request. A
complete 114-task reward needs an appropriately configured evaluator for them;
this harness does not claim that score. Multiple seeds are supported, e.g.
`--seeds 300 301 302 303`; no pass^k estimate is emitted from incomplete coverage.
Use `--num-tasks 0` with multiple explicit IDs to preserve the whole ID selection.

Resume with the identical command plus `--resume`. Completed, failed, timeout,
and excluded rows are preserved. Tasks deferred by `--total-timeout-seconds` are
retried on resume. Resume rejects changed models, source, task selection, seeds,
or budgets; use a new output directory for a different experiment.

`--official-source /path/to/pinned/checkout` and optional `--tau2-python
/path/to/its/.venv/bin/python` support a runtime outside the project. The default
transport is LiteLLM `ollama_chat/<model>` at the loopback Ollama HTTP origin.
`--transport openai-compatible` uses `openai/<model>` against that same local
origin's `/v1` endpoint. No cloud endpoint is accepted. Model temperature is 0,
reasoning is requested disabled, generation is capped at 512 tokens, context at 4096 tokens
for the native transport, and retries are disabled. These are small-machine
baseline settings, not the upstream leaderboard configuration.

The default `--num-ctx 4096` limits memory for smaller experiments. On the 16 GB
development machine, run inference serially with the same loaded model for
agent and user. The official
policy is 6699 characters and the 16 tool schemas total 12311 characters before
the conversation. A 4096-token context can truncate policy or conversation
history; a score from that configuration is a memory-constrained local baseline,
not a comparison under the upstream leaderboard's model/context settings.
The official-interaction smoke above explicitly requests 8192 tokens to fit the
policy/tool preamble, keeps inference serial, and uses the same model for both
participants. Check memory pressure before running it; a larger context can
increase the loaded model's resident memory.

## Artifacts and interpretation

Each task runs in its own subprocess with a hard wall-clock limit. The upstream
step/error/time limits also apply. `checkpoint.json` is atomically updated after
every row, and `report.json` contains the same aggregate plus provenance and all
requested task IDs. Per-task logs, requests containing only task IDs/config,
and official conversation/tool trajectories are saved in separate directories.
Trajectories are checkpointed after each finished official step; a timeout
during the first model call can have no trajectory yet.

`completed_interactions` counts only official user/agent stops. A step limit,
tool-error limit, or model error is a separate status, even if the official
scorer assigns it 0. A hard-killed worker is unscored. Judge-dependent exclusions
and tasks not started before the total budget expires are also unscored.

`mean_official_reward_over_scored` uses only rows actually scored by the official
scorer; always read it alongside score coverage and status counts.
`reward_lower_bound_over_requested` divides obtained rewards by every requested
simulation, treating missing scores as zero for an explicitly labeled diagnostic
lower bound. It is not official benchmark reward or pass^k. Static task summaries,
synthetic workflow evaluations, and isolated ReturnFlow component scores are
not represented as complete official tau2 interactions.

## Actual bounded local smoke, 2026-10-14

Task 48 / train / seed 300 was attempted with the command above, using the separately
verified pinned source at `/private/tmp/returnflow-tau2-dd8757d4`. Both participants used
Qwen3:4B at 8K context, temperature 0, 512 maximum output tokens, and no retries.
The 180-second hard deadline ended the worker after 11 completed official steps and
12 checkpointed messages, including one identity-lookup tool call. It did not reach
official scoring: coverage 0/1, official reward `null`, status `timeout`.

The model emitted verbose deliberation and repeated capped outputs despite requesting
disabled reasoning. A separate local request capture using the pinned LiteLLM version
confirmed that `reasoning_effort="none"` becomes top-level `think:false`. This validates
request mapping, not compliance of the installed model/template. No agent policy, gold
criteria, or scorer was changed to produce a better result. This is an observed integration
limitation, not a successful benchmark completion. Resolve it on train before a larger run.

Aggregate and partial-trajectory counters are in
[the public smoke report](results/public-eval/tau2-smoke.json). Raw checkpoints/logs remain
under ignored `data/evaluation_runs/tau2-smoke-2026-10-14/`. Measured token counters cover
only the ten finished checkpointed model calls and exclude any in-flight killed call.
