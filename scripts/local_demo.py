"""Supervise a loopback-only SQLite demo without Docker, PostgreSQL, or Qdrant."""

import argparse
import errno
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]


def demo_environment(database: Path, provider: str, api_port: int, ui_port: int) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        DATABASE_URL=f"sqlite+pysqlite:///{database.resolve()}",
        ENVIRONMENT="local-demo",
        LLM_PROVIDER=provider,
        LLM_MODEL="qwen3:4b",
        LLM_BASE_URL="http://127.0.0.1:11434/v1",
        LLM_API_KEY="",
        LLM_TIMEOUT_SECONDS="60",
        POLICY_RETRIEVER="lexical",
        POLICY_GENERATOR="extractive",
        CORS_ORIGINS=json.dumps([f"http://127.0.0.1:{ui_port}", f"http://localhost:{ui_port}"]),
        RETURNFLOW_API_ORIGIN=f"http://127.0.0.1:{api_port}",
        VITE_API_BASE_URL="",
    )
    return environment


def require_free_port(port: int) -> None:
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise ValueError(f"Cannot bind loopback port {port}: {error.strerror}") from error
            raise ValueError(
                f"Port {port} is busy; stop its owner or choose a different port"
            ) from error


def stop_children(children: list[subprocess.Popen[Any]]) -> None:
    # Only terminate process groups created by this invocation, never global processes.
    for child in reversed(children):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
    for child in reversed(children):
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/local_demo/returnflow.db")
    parser.add_argument("--provider", choices=("rules", "ollama", "dashscope"), default="ollama")
    parser.add_argument("--workflow", choices=("apparel", "legacy"), default="apparel")
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=5173)
    parser.add_argument("--api-only", action="store_true")
    args = parser.parse_args()
    if not all(1024 <= port <= 65535 for port in (args.api_port, args.ui_port)):
        parser.error("Ports must be between 1024 and 65535")
    if not args.api_only and args.api_port == args.ui_port:
        parser.error("API and UI ports must differ")
    try:
        require_free_port(args.api_port)
        if not args.api_only:
            require_free_port(args.ui_port)
    except ValueError as error:
        parser.error(str(error))
    if not args.api_only and (
        shutil.which("npm") is None or not (ROOT / "frontend/node_modules/.bin/vite").exists()
    ):
        parser.error("Install Node.js and run npm ci in frontend/, or choose --api-only")
    database = args.database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    inherited_base = os.environ.get("LLM_BASE_URL", "")
    environment = demo_environment(database, args.provider, args.api_port, args.ui_port)
    if args.provider == "dashscope":
        model = args.model or "qwen3.7-flash"
        ollama_bases = {"", "http://127.0.0.1:11434/v1", "http://localhost:11434/v1"}
        base_url = (
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            if inherited_base.rstrip("/") in ollama_bases
            else inherited_base.rstrip("/")
        )
    else:
        model = args.model or "qwen3:4b"
        base_url = environment["LLM_BASE_URL"]
    environment.update(
        WORKFLOW_MODE=args.workflow,
        DEMO_ENABLED="true",
        DEMO_SESSION_SECRET=os.environ.get("DEMO_SESSION_SECRET") or secrets.token_hex(32),
        EXTRACTION_MODE="guided" if args.provider == "rules" else "llm",
        LLM_MODEL=model,
        LLM_BASE_URL=base_url,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "scripts.seed_data"], cwd=ROOT, env=environment, check=True
    )
    if args.workflow == "apparel":
        subprocess.run(
            [sys.executable, "-m", "scripts.seed_demo_accounts"],
            cwd=ROOT,
            env=environment,
            check=True,
        )
    children: list[subprocess.Popen[Any]] = []
    try:
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ],
            cwd=ROOT,
            env=environment,
            start_new_session=True,
        )
        children.append(api)
        deadline = monotonic() + 20
        with httpx.Client(trust_env=False, timeout=1) as client:
            while True:
                if api.poll() is not None:
                    raise RuntimeError("API exited before becoming ready")
                try:
                    response = client.get(f"http://127.0.0.1:{args.api_port}/ready")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if monotonic() >= deadline:
                    raise RuntimeError("API did not become ready within 20 seconds")
                sleep(0.1)
        if not args.api_only:
            children.append(
                subprocess.Popen(
                    [
                        "npm",
                        "run",
                        "dev",
                        "--",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(args.ui_port),
                        "--strictPort",
                    ],
                    cwd=ROOT / "frontend",
                    env=environment,
                    start_new_session=True,
                )
            )
        print(f"Demo database: {database}", flush=True)
        print(f"API: http://127.0.0.1:{args.api_port}/docs", flush=True)
        if not args.api_only:
            print(f"UI: http://127.0.0.1:{args.ui_port}", flush=True)
        print(
            "Ctrl+C stops this demo's API/UI. Data persist; no real refund is performed.",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            sleep(0.25)
        raise RuntimeError("A demo service exited; stopping the remaining owned services")
    except KeyboardInterrupt:
        pass
    finally:
        stop_children(children)


if __name__ == "__main__":
    main()
