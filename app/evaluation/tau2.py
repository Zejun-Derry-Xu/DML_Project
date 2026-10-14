"""Bounded, local-only execution of the pinned official tau2 retail simulator.

The production application does not import tau2 or LiteLLM. Each simulation runs
in the official checkout's separate Python environment. This evaluates the
official LLMAgent baseline, not ReturnFlow's extraction or policy components.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

OFFICIAL_REVISION = "dd8757d4c8791dad7b3cdaf02a105a3d5f9d86bd"
SCHEMA_VERSION = 1
RETAIL_FILES = ("tasks.json", "db.json", "policy.md", "split_tasks.json")


@dataclass(frozen=True)
class Tau2Config:
    official_source: Path
    output_dir: Path
    tau2_python: Path | None = None
    data_dir: Path | None = None
    split: str = "train"
    task_ids: tuple[str, ...] = ()
    num_tasks: int | None = 1
    seeds: tuple[int, ...] = (300,)
    model: str = "qwen3:4b"
    user_model: str = "qwen3:4b"
    transport: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    max_steps: int = 40
    max_errors: int = 5
    task_timeout_seconds: float = 180.0
    call_timeout_seconds: float = 60.0
    total_timeout_seconds: float | None = None
    max_tokens: int = 512
    num_ctx: int = 4096

    def validate(self) -> None:
        parsed = urlsplit(self.ollama_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ollama_url must be a loopback HTTP origin")
        if self.transport not in {"ollama", "openai-compatible"}:
            raise ValueError("unsupported local transport")
        for model in (self.model, self.user_model):
            if not model.strip() or model.startswith(("http:", "https:")):
                raise ValueError("provide an installed Ollama model name")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be nonempty and unique")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task IDs must be unique")
        if self.num_tasks is not None and self.num_tasks < 1:
            raise ValueError("num_tasks must be positive or None for all tasks")
        for name in ("max_steps", "max_errors", "max_tokens", "num_ctx"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        for name in ("task_timeout_seconds", "call_timeout_seconds", "total_timeout_seconds"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")

    def serialized(self) -> dict[str, Any]:
        return {
            key: str(value.absolute()) if isinstance(value, Path) else value
            for key, value in asdict(self).items()
        }

    @property
    def python(self) -> Path:
        return self.tau2_python or self.official_source / ".venv" / "bin" / "python"

    @property
    def data_root(self) -> Path:
        return self.data_dir or self.official_source / "data"


def write_json(path: Path, value: Any) -> None:
    """Atomically update checkpoints so interrupted runs remain resumable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def verify_source(config: Tau2Config) -> dict[str, Any]:
    """Reject an unpinned or edited runtime instead of silently changing the benchmark."""
    revision = subprocess.check_output(
        ["git", "-C", str(config.official_source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != OFFICIAL_REVISION:
        raise ValueError(f"official source must be pinned to {OFFICIAL_REVISION}; got {revision}")
    changed = subprocess.check_output(
        [
            "git",
            "-C",
            str(config.official_source),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "src",
            "pyproject.toml",
            "uv.lock",
            "data/tau2/domains/retail",
        ],
        text=True,
    )
    if changed.strip():
        raise ValueError("official source, lockfile, or retail data has local modifications")
    if not config.python.is_file():
        raise ValueError(f"isolated tau2 Python is missing: {config.python}")
    retail = config.data_root / "tau2" / "domains" / "retail"
    hashes = {}
    for name in RETAIL_FILES:
        content = (retail / name).read_bytes()
        # External data must match the pinned checkout, including policy and DB.
        expected = subprocess.check_output(
            [
                "git",
                "-C",
                str(config.official_source),
                "show",
                f"HEAD:data/tau2/domains/retail/{name}",
            ]
        )
        if content != expected:
            raise ValueError(f"{name} does not match the pinned official source")
        hashes[name] = hashlib.sha256(content).hexdigest()
    return {
        "repository": "https://github.com/sierra-research/tau2-bench",
        "revision": revision,
        "retail_sha256": hashes,
    }


def select_tasks(config: Tau2Config) -> list[dict[str, Any]]:
    retail = config.data_root / "tau2" / "domains" / "retail"
    tasks: list[dict[str, Any]] = json.loads((retail / "tasks.json").read_text())
    splits = json.loads((retail / "split_tasks.json").read_text())
    if config.split != "all":
        if config.split not in splits:
            raise ValueError(f"unknown split {config.split!r}; choose {sorted(splits)} or all")
        allowed = set(splits[config.split])
        tasks = [task for task in tasks if task["id"] in allowed]
    if config.task_ids:
        by_id = {task["id"]: task for task in tasks}
        missing = set(config.task_ids) - by_id.keys()
        if missing:
            raise ValueError(f"task IDs not in split {config.split}: {sorted(missing)}")
        tasks = [by_id[task_id] for task_id in config.task_ids]
    if config.num_tasks is not None:
        tasks = tasks[: config.num_tasks]
    return tasks


def needs_external_judge(task: dict[str, Any]) -> bool:
    criteria = task.get("evaluation_criteria") or {}
    # Empty assertions are an official deterministic pass even if the basis lists NL_ASSERTION.
    return "NL_ASSERTION" in criteria.get("reward_basis", []) and bool(
        criteria.get("nl_assertions")
    )


def agent_kwargs(environment: Any, config: Tau2Config) -> dict[str, Any]:
    """The agent receives only public policy/tools, never Task or evaluation criteria."""
    model, arguments = local_llm_settings(config, config.model)
    return {
        "tools": environment.get_tools(),
        "domain_policy": environment.get_policy(),
        "llm": model,
        "llm_args": arguments,
    }


def local_llm_settings(config: Tau2Config, model: str) -> tuple[str, dict[str, Any]]:
    arguments: dict[str, Any] = {
        "temperature": 0.0,
        "timeout": config.call_timeout_seconds,
        "num_retries": 0,
        "max_tokens": config.max_tokens,
    }
    if config.transport == "ollama":
        arguments.update(
            {
                "api_base": config.ollama_url.rstrip("/"),
                # LiteLLM maps reasoning_effort=none to top-level think=false;
                # provider-specific num_ctx is placed in Ollama options.
                "reasoning_effort": "none",
                "num_ctx": config.num_ctx,
            }
        )
        return f"ollama_chat/{model}", arguments
    arguments.update(
        {
            "api_base": config.ollama_url.rstrip("/") + "/v1",
            "api_key": "ollama",
            "extra_body": {"think": False},
        }
    )
    return f"openai/{model}", arguments


def subprocess_environment(config: Tau2Config) -> dict[str, str]:
    environment = os.environ.copy()
    # Prevent .env and pricing-map initialization from reaching remote services.
    environment.update(
        {
            "PYTHON_DOTENV_DISABLED": "1",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "LITELLM_TELEMETRY": "False",
            "TAU2_DATA_DIR": str(config.data_root.resolve()),
            "PYTHONPATH": str(config.official_source.resolve() / "src"),
        }
    )
    for key in list(environment):
        if key.endswith(("_API_KEY", "_ACCESS_TOKEN")) or key in {
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        }:
            environment.pop(key)
    environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
    return environment


def aggregate(results: list[dict[str, Any]], requested: int) -> dict[str, Any]:
    counts = Counter(row["status"] for row in results)
    scored = [row["official_reward"] for row in results if row.get("official_reward") is not None]
    reward_sum = sum(scored)
    attempted = sum(bool(row.get("attempted")) for row in results)
    return {
        "requested_simulations": requested,
        "recorded_simulations": len(results),
        "attempted_simulations": attempted,
        "completed_interactions": counts["completed"],
        "officially_scored_simulations": len(scored),
        "unscored_simulations": requested - len(scored),
        "status_counts": dict(sorted(counts.items())),
        "official_reward_sum": reward_sum,
        "mean_official_reward_over_scored": reward_sum / len(scored) if scored else None,
        # Missing results and excluded tasks are not successes. This is a coverage-aware
        # diagnostic lower bound, NOT official benchmark reward or pass^k.
        "reward_lower_bound_over_requested": reward_sum / requested if requested else None,
        "score_coverage": len(scored) / requested if requested else None,
        "official_pass_k": None,
    }


def run_one(config: Tau2Config, task_id: str, seed: int, timeout: float) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        raise ValueError("unsafe task ID for artifact filename")
    stem = f"task-{task_id}-seed-{seed}"
    request_path = config.output_dir / "requests" / f"{stem}.json"
    result_path = config.output_dir / "results" / f"{stem}.json"
    trajectory_path = config.output_dir / "trajectories" / f"{stem}.json"
    log_path = config.output_dir / "logs" / f"{stem}.log"
    write_json(
        request_path,
        {
            "config": config.serialized(),
            "task_id": task_id,
            "seed": seed,
            "result_path": str(result_path.resolve()),
            "trajectory_path": str(trajectory_path.resolve()),
        },
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_tau2.py"
    started = time.monotonic()
    row: dict[str, Any] = {
        "task_id": task_id,
        "seed": seed,
        "attempted": True,
        "official_reward": None,
        "trajectory": str(trajectory_path.resolve()),
        "log": str(log_path.resolve()),
    }
    with log_path.open("w") as log:
        try:
            process = subprocess.run(
                [
                    str(config.python.absolute()),
                    str(script),
                    "--worker-request",
                    str(request_path.resolve()),
                ],
                cwd=config.official_source,
                env=subprocess_environment(config),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            row.update(
                status="timeout", error=f"worker exceeded {timeout:.1f}s hard wall-clock limit"
            )
        else:
            if result_path.exists():
                row.update(json.loads(result_path.read_text()))
            else:
                row.update(
                    status="error", error=f"worker exited {process.returncode} without a result"
                )
    row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_json(result_path, row)
    return row


def run_evaluation(config: Tau2Config, *, resume: bool = False) -> dict[str, Any]:
    config.validate()
    provenance = verify_source(config)
    provenance["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    tasks = select_tasks(config)
    if not tasks:
        raise ValueError("selection contains no tasks")
    plan = [(task, seed) for task in tasks for seed in config.seeds]
    settings = json.loads(json.dumps(config.serialized()))
    fingerprint = hashlib.sha256(
        json.dumps({"config": settings, "source": provenance}, sort_keys=True).encode()
    ).hexdigest()
    checkpoint_path = config.output_dir / "checkpoint.json"
    if checkpoint_path.exists():
        if not resume:
            raise ValueError("checkpoint exists; use --resume or a new output directory")
        report: dict[str, Any] = json.loads(checkpoint_path.read_text())
        if report["fingerprint"] != fingerprint:
            raise ValueError("resume configuration/source differs from the checkpoint")
    else:
        report = {
            "schema_version": SCHEMA_VERSION,
            "evaluation": "official_tau2_retail_local_baseline",
            "agent_implementation": "official LLMAgent; not ReturnFlow application",
            "scoring": "official EvaluationType.ALL; no external NL judge",
            "fingerprint": fingerprint,
            "config": settings,
            "source": provenance,
            "requested_task_ids": [task["id"] for task in tasks],
            "requested_tasks": len(tasks),
            "requested_simulations": len(plan),
            "results": [],
        }
    # Budget skips are retried by --resume. Other terminal rows are not silently rerun.
    existing = {
        (row["task_id"], row["seed"]): row
        for row in report["results"]
        if row["status"] != "not_started_budget"
    }
    started = time.monotonic()
    for task, seed in plan:
        key = (task["id"], seed)
        if key in existing:
            continue
        row: dict[str, Any] = {
            "task_id": task["id"],
            "seed": seed,
            "attempted": False,
            "official_reward": None,
        }
        remaining = (
            None
            if config.total_timeout_seconds is None
            else (config.total_timeout_seconds - (time.monotonic() - started))
        )
        if needs_external_judge(task):
            row.update(
                status="excluded_nl_assertions",
                error="nonempty official NL assertions require an evaluator; none configured",
            )
        elif remaining is not None and remaining <= 0:
            row.update(status="not_started_budget", error="total run wall-clock budget exhausted")
        else:
            timeout = config.task_timeout_seconds
            if remaining is not None:
                timeout = min(timeout, remaining)
            row = run_one(config, task["id"], seed, timeout)
        existing[key] = row
        report["results"] = [
            existing[(item["id"], item_seed)]
            for item, item_seed in plan
            if (item["id"], item_seed) in existing
        ]
        report["aggregate"] = aggregate(report["results"], len(plan))
        write_json(checkpoint_path, report)
    report["aggregate"] = aggregate(report["results"], len(plan))
    report["invocation_elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_json(checkpoint_path, report)
    write_json(config.output_dir / "report.json", report)
    return report


def worker(request_path: Path) -> None:
    """Only called in the isolated official runtime, never in the production process."""
    request = json.loads(request_path.read_text())
    values = request["config"]
    for key in ("official_source", "output_dir", "tau2_python", "data_dir"):
        if values.get(key) is not None:
            values[key] = Path(values[key])
    config = Tau2Config(**values)
    config.validate()
    result_path, trajectory_path = Path(request["result_path"]), Path(request["trajectory_path"])
    row: dict[str, Any] = {"status": "error", "official_reward": None}
    try:
        # Optional packages exist only in the isolated official runtime.
        from loguru import logger  # type: ignore[import-not-found]
        from tau2.agent.llm_agent import LLMAgent  # type: ignore[import-not-found]
        from tau2.domains.retail.environment import (  # type: ignore[import-not-found]
            get_environment,
            get_tasks,
        )
        from tau2.evaluator.evaluator import (  # type: ignore[import-not-found]
            EvaluationType,
            evaluate_simulation,
        )
        from tau2.orchestrator.orchestrator import Orchestrator  # type: ignore[import-not-found]
        from tau2.user.user_simulator import UserSimulator  # type: ignore[import-not-found]

        row["runtime_versions"] = {
            "python": sys.version.split()[0],
            "tau2": importlib.metadata.version("tau2"),
            "litellm": importlib.metadata.version("litellm"),
            "websockets": importlib.metadata.version("websockets"),
        }
        logger.remove()
        logger.add(lambda message: print(message, end="", flush=True), level="ERROR")
        task = next(
            task for task in get_tasks(task_split_name=None) if task.id == request["task_id"]
        )
        if needs_external_judge(task.model_dump(mode="json")):
            raise ValueError("worker refuses tasks requiring an external NL judge")
        environment = get_environment()
        agent = LLMAgent(**agent_kwargs(environment, config))
        user_model, user_arguments = local_llm_settings(config, config.user_model)
        user = UserSimulator(
            tools=None,
            instructions=str(task.user_scenario),
            llm=user_model,
            llm_args=user_arguments,
        )

        class CheckpointOrchestrator(Orchestrator):  # type: ignore[misc]
            def step(self) -> None:
                super().step()
                write_json(
                    trajectory_path,
                    {
                        "task_id": task.id,
                        "seed": request["seed"],
                        "partial": True,
                        "steps": self.step_count,
                        "messages": [
                            message.model_dump(mode="json") for message in self.get_trajectory()
                        ],
                    },
                )

        orchestrator = CheckpointOrchestrator(
            domain="retail",
            agent=agent,
            user=user,
            environment=environment,
            task=task,
            max_steps=config.max_steps,
            max_errors=config.max_errors,
            seed=request["seed"],
            timeout=config.task_timeout_seconds,
        )
        simulation = orchestrator.run()
        simulation.policy = environment.get_policy()
        write_json(
            trajectory_path, {"partial": False, "simulation": simulation.model_dump(mode="json")}
        )
        reward = evaluate_simulation(
            simulation=simulation,
            task=task,
            evaluation_type=EvaluationType.ALL,
            solo_mode=False,
            domain="retail",
        )
        simulation.reward_info = reward
        write_json(
            trajectory_path, {"partial": False, "simulation": simulation.model_dump(mode="json")}
        )
        termination = simulation.termination_reason.value
        row.update(
            status="completed" if termination in {"user_stop", "agent_stop"} else termination,
            termination_reason=termination,
            official_reward=reward.reward,
            reward_info=reward.model_dump(mode="json"),
            message_count=len(simulation.messages),
            tool_call_count=sum(
                len(message.tool_calls or [])
                for message in simulation.messages
                if hasattr(message, "tool_calls")
            ),
        )
    except Exception as error:
        row.update(error=f"{type(error).__name__}: {error}")
    write_json(result_path, row)
