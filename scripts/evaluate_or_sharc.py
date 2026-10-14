"""Reproducible OR-ShARC component experiments with native local Ollama calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from app.evaluation.or_sharc import (
    EVALUATOR_VERSION,
    READER_SYSTEM_PROMPT,
    SOURCE_REPOSITORY,
    BM25Retriever,
    Checkpoint,
    OllamaReader,
    OllamaVectorRetriever,
    Retriever,
    by_seen,
    example_metadata,
    file_sha256,
    load_documents,
    load_examples,
    reader_metrics,
    require_local_ollama,
    retrieval_metrics,
    seeded_sample,
    utc_now,
    validate_corpus,
)

ROOT = Path(__file__).resolve().parents[1]


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parser() -> argparse.ArgumentParser:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument(
        "--mode", choices=("retrieval", "reader", "integrated", "all"), default="retrieval"
    )
    args.add_argument("--split", choices=("train", "dev", "test"), default="test")
    args.add_argument("--data-dir", type=Path, default=ROOT / "data/evaluation_sources/or_sharc")
    args.add_argument("--retriever", choices=("bm25", "ollama"), default="bm25")
    args.add_argument(
        "--sample-size",
        type=_positive,
        default=30,
        help="Fixed seed model sample; retrieval always covers the whole split",
    )
    args.add_argument("--seed", type=int, default=42)
    args.add_argument(
        "--top-k",
        type=_positive,
        default=3,
        help="Integrated reader context size (reader comparison uses top-1)",
    )
    args.add_argument("--model", default="qwen3:4b")
    args.add_argument("--embedding-model", default="embeddinggemma")
    args.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args.add_argument("--timeout-seconds", type=float, default=90)
    args.add_argument("--num-predict", type=_positive, default=220)
    args.add_argument(
        "--time-budget-seconds",
        type=float,
        default=600,
        help="Per-invocation wall time; individual HTTP calls get the remaining timeout",
    )
    args.add_argument(
        "--limit",
        type=_positive,
        help=(
            "Maximum new model calls in this invocation; resumable "
            "without changing the fixed sample"
        ),
    )
    args.add_argument(
        "--run-dir",
        type=Path,
        help=(
            "Private manifest/checkpoint directory; defaults to timestamped "
            "data/evaluation_runs/or_sharc"
        ),
    )
    args.add_argument("--resume", action="store_true")
    args.add_argument(
        "--summary",
        type=Path,
        help="Public aggregate JSON; defaults to docs/results/<run-directory-name>.json",
    )
    return args


def _git_revision() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _sources(data_dir: Path, split: str) -> dict[str, Any]:
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {row["name"]: row["sha256"] for row in manifest["files"]}
    checksums = {}
    for name in ("id2snippet.json", f"open_retrieval_sharc_{split}.json"):
        actual = file_sha256(data_dir / name)
        if expected.get(name) != actual:
            raise ValueError(f"Source checksum does not match pinned manifest: {name}")
        checksums[name] = actual
    return {
        "repository": SOURCE_REPOSITORY,
        "revision": manifest["revision"],
        "license": manifest.get("license"),
        "files_sha256": checksums,
        "manifest_sha256": file_sha256(manifest_path),
    }


def _model_provenance(args: argparse.Namespace) -> dict[str, Any] | None:
    names = ([args.model] if args.mode != "retrieval" else []) + (
        [args.embedding_model] if args.retriever == "ollama" else []
    )
    if not names:
        return None
    url = require_local_ollama(args.ollama_url)
    try:
        with httpx.Client(timeout=min(args.timeout_seconds, 5), trust_env=False) as client:
            response = client.get(f"{url}/api/tags")
            response.raise_for_status()
            available = response.json()["models"]
            return {
                name: next(
                    {key: model.get(key) for key in ("name", "digest", "size", "details")}
                    for model in available
                    if model.get("name") in {name, f"{name}:latest"}
                )
                for name in names
            }
    except (httpx.HTTPError, ValueError, KeyError, TypeError, StopIteration) as exc:
        return {"unavailable": str(exc), "requested_names": names}


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.timeout_seconds <= 0 or args.time_budget_seconds <= 0:
        raise ValueError("Timeout and time budget must be positive")
    if args.top_k > 5:
        raise ValueError("top-k must be at most 5 to match the citation schema")
    if args.resume and args.run_dir is None:
        raise ValueError("--resume requires the exact --run-dir")
    started = perf_counter()
    started_at = utc_now()
    run_dir = (
        args.run_dir
        or ROOT
        / "data/evaluation_runs/or_sharc"
        / f"or-sharc-{args.mode}-{args.split}-{started_at[:19].replace(':', '').replace('-', '')}"
    )
    run_dir = run_dir.resolve()
    summary_path = (args.summary or ROOT / "docs/results" / f"{run_dir.name}.json").resolve()
    documents = load_documents(args.data_dir / "id2snippet.json")
    examples = load_examples(args.data_dir / f"open_retrieval_sharc_{args.split}.json")
    validate_corpus(examples, documents)
    selected = seeded_sample(examples, args.sample_size, args.seed)
    sources = _sources(args.data_dir, args.split)
    model_provenance = _model_provenance(args)
    code_files = (ROOT / "app/evaluation/or_sharc.py", Path(__file__).resolve())
    parameters = {
        "evaluator_version": EVALUATOR_VERSION,
        "split": args.split,
        "mode": args.mode,
        "retriever": args.retriever,
        "bm25": {
            "k1": 1.2,
            "b": 0.75,
            "tokenizer": "ascii_alphanumeric_casefold",
            "query_terms": "unique",
        },
        "query_fields": ["question", "scenario", "history"],
        "model": args.model if args.mode != "retrieval" else None,
        "embedding_model": args.embedding_model if args.retriever == "ollama" else None,
        "ollama_url": args.ollama_url
        if args.mode != "retrieval" or args.retriever == "ollama"
        else None,
        "sample_size": args.sample_size,
        "seed": args.seed,
        "top_k": args.top_k,
        "num_predict": args.num_predict,
        "temperature": 0,
        "think": False,
        "reader_prompt_sha256": hashlib.sha256(READER_SYSTEM_PROMPT.encode()).hexdigest(),
        "selected_ids": [example.utterance_id for example in selected],
        "selected_ids_sha256": hashlib.sha256(
            "\n".join(example.utterance_id for example in selected).encode()
        ).hexdigest(),
        "code_sha256": {str(path.relative_to(ROOT)): file_sha256(path) for path in code_files},
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        if not args.resume:
            raise ValueError("Run manifest exists; use a new directory or --resume")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest["parameters"] != parameters
            or manifest["sources"] != sources
            or manifest["model_provenance"] != model_provenance
        ):
            raise ValueError(
                "Cannot resume: source, sample, model, protocol or evaluator code changed"
            )
    else:
        if args.resume:
            raise ValueError("Cannot resume a directory without a run manifest")
        manifest = {
            "started_at": started_at,
            "sources": sources,
            "parameters": parameters,
            "model_provenance": model_provenance,
            "git_revision": _git_revision(),
            "corpus_document_count": len(documents),
            "split": example_metadata(examples),
            "model_sample": example_metadata(selected),
            "invocations": [],
        }
    manifest["invocations"].append(
        {
            "started_at": started_at,
            "time_budget_seconds": args.time_budget_seconds,
            "timeout_seconds": args.timeout_seconds,
            "limit_new_model_calls": args.limit,
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checkpoint = Checkpoint(run_dir / "predictions.jsonl", resume=args.resume)
    deadline = started + args.time_budget_seconds
    stopped_reason = None
    new_calls = 0
    retriever_initialization_error = None
    embedding_calls: list[dict[str, Any]] = []
    document_by_id = {document.id: document for document in documents}
    with httpx.Client(timeout=args.timeout_seconds, trust_env=False) as client:
        retriever: Retriever | None
        if args.retriever == "bm25":
            retriever = BM25Retriever(documents)
        else:
            # Cache is run-local and tied to model name and exact corpus content.
            client.timeout = httpx.Timeout(
                min(args.timeout_seconds, max(0.001, deadline - perf_counter()))
            )
            try:
                retriever = OllamaVectorRetriever(
                    documents,
                    client,
                    url=args.ollama_url,
                    model=args.embedding_model,
                    cache_path=run_dir / "document-embeddings.json",
                    deadline=deadline,
                )
                embedding_calls = retriever.calls
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                retriever = None
                retriever_initialization_error = str(exc)
        retrieval_records = checkpoint.experiment("retrieval")
        for example in examples:
            if example.utterance_id in retrieval_records:
                continue
            if perf_counter() >= deadline:
                stopped_reason = "time_budget"
                break
            query_started = perf_counter()
            record: dict[str, Any] = {
                "experiment": "retrieval",
                "utterance_id": example.utterance_id,
                "tree_id": example.tree_id,
                "gold_snippet_id": example.target.gold_snippet_id,
                "status": "ok",
                "retrieved_ids": [],
            }
            try:
                if retriever is None:
                    raise ValueError(
                        f"Embedding corpus initialization failed: {retriever_initialization_error}"
                    )
                client.timeout = httpx.Timeout(
                    min(args.timeout_seconds, max(0.001, deadline - perf_counter()))
                )
                # Full ranking makes MRR untruncated. Context uses the first k IDs only.
                hits = retriever.search(example.inputs.retrieval_query(), limit=len(documents))
                record["retrieved_ids"] = [hit.document.id for hit in hits]
                record["top_5_scores"] = [hit.score for hit in hits[:5]]
            except httpx.TimeoutException as exc:
                record.update(status="timeout", error=str(exc))
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                record.update(status="retrieval_error", error=str(exc))
            record["latency_ms"] = (perf_counter() - query_started) * 1000
            checkpoint.append(record)
            retrieval_records[example.utterance_id] = record
        experiments = []
        if args.mode in {"reader", "all"}:
            experiments += ["reader_oracle", "reader_retrieved"]
        if args.mode in {"integrated", "all"}:
            experiments += ["integrated"]
        reader = (
            OllamaReader(
                client, url=args.ollama_url, model=args.model, num_predict=args.num_predict
            )
            if experiments
            else None
        )
        # Interleave contexts per selected example so time-limited runs stay paired.
        for example in selected if experiments else []:
            for experiment in experiments:
                if (experiment, example.utterance_id) in checkpoint.records:
                    continue
                if perf_counter() >= deadline or args.limit is not None and new_calls >= args.limit:
                    stopped_reason = (
                        "time_budget" if perf_counter() >= deadline else "model_call_limit"
                    )
                    break
                retrieval = retrieval_records.get(example.utterance_id)
                if experiment == "reader_oracle":
                    context = [document_by_id[example.target.gold_snippet_id]]
                elif retrieval is None or retrieval["status"] != "ok":
                    checkpoint.append(
                        {
                            "experiment": experiment,
                            "utterance_id": example.utterance_id,
                            "status": "retrieval_error",
                            "prediction": None,
                            "context_ids": [],
                            "latency_ms": 0,
                            "error": "No successful retrieval checkpoint",
                        }
                    )
                    continue
                else:
                    count = 1 if experiment == "reader_retrieved" else args.top_k
                    context = [
                        document_by_id[identity] for identity in retrieval["retrieved_ids"][:count]
                    ]
                client.timeout = httpx.Timeout(
                    min(args.timeout_seconds, max(0.001, deadline - perf_counter()))
                )
                assert reader is not None
                record = reader.predict(example.inputs, context)
                record.update(
                    experiment=experiment,
                    utterance_id=example.utterance_id,
                    tree_id=example.tree_id,
                    gold_snippet_id=example.target.gold_snippet_id,
                    gold_decision=example.target.decision,
                    inputs=example.inputs.to_dict(),
                    context_documents=[
                        {"id": document.id, "text": document.text} for document in context
                    ],
                )
                if experiment == "integrated":
                    assert retrieval is not None
                    record["reader_latency_ms"] = record["latency_ms"]
                    record["retrieval_latency_ms"] = retrieval["latency_ms"]
                    record["latency_ms"] += retrieval["latency_ms"]
                checkpoint.append(record)
                new_calls += 1
            if stopped_reason:
                break
    report: dict[str, Any] = {
        "benchmark": "OR-ShARC",
        "evaluator_version": EVALUATOR_VERSION,
        "started_at": manifest["started_at"],
        "updated_at": utc_now(),
        "sources": sources,
        "model_provenance": model_provenance,
        "parameters": {key: value for key, value in parameters.items() if key != "selected_ids"},
        "corpus_document_count": len(documents),
        "split": example_metadata(examples),
        "model_sample": example_metadata(selected) if experiments else None,
        "model_sample_note": (
            "Uniform fixed-seed utterance sample chosen by IDs only; labels never stratify "
            "selection. Shared tree groups may recur."
        ),
        "retrieval": retrieval_metrics(examples, retrieval_records),
        "retrieval_by_seen": by_seen(examples, retrieval_records),
        "experiments": {},
        "new_model_calls": new_calls,
        "retriever_initialization_error": retriever_initialization_error,
        "embedding_calls_this_invocation": {
            "count": len(embedding_calls),
            "input_count": sum(call["input_count"] for call in embedding_calls),
            "prompt_tokens_total_measured": sum(
                call["prompt_tokens"]
                for call in embedding_calls
                if isinstance(call["prompt_tokens"], int)
            ),
            "prompt_tokens_unknown_call_count": sum(
                not isinstance(call["prompt_tokens"], int) for call in embedding_calls
            ),
            "note": (
                "Embedding cost is invocation-local; cached document vectors "
                "do not incur new calls."
            ),
        },
        "invocation_elapsed_seconds": perf_counter() - started,
        "stopped_reason": stopped_reason,
        "checkpoint": str(checkpoint.path.relative_to(ROOT))
        if checkpoint.path.is_relative_to(ROOT)
        else str(checkpoint.path),
        "limitations": [
            "BM25 is a frozen lexical baseline, not the published OR-ShARC model.",
            "Three-way decision accuracy is distinct from follow-up question quality, "
            "which is not scored automatically.",
            "Citations score gold document IDs only; clause entailment and textual "
            "faithfulness require manual review.",
            "Native Ollama token counts are measured when supplied; missing provider "
            "counts remain unknown.",
            "Model samples and partial runs must not be represented as complete "
            "test-set model performance.",
        ],
    }
    for experiment in experiments:
        records = checkpoint.experiment(experiment)
        report["experiments"][experiment] = {
            **reader_metrics(selected, records),
            "by_seen": by_seen(selected, records, reader=True),
            "context": "gold public snippet (oracle)"
            if experiment == "reader_oracle"
            else "retrieved top-1"
            if experiment == "reader_retrieved"
            else f"retrieved top-{args.top_k}",
        }
    if {"reader_oracle", "reader_retrieved"} <= set(experiments):
        oracle = checkpoint.experiment("reader_oracle")
        retrieved = checkpoint.experiment("reader_retrieved")
        paired = [
            example
            for example in selected
            if example.utterance_id in oracle and example.utterance_id in retrieved
        ]
        report["paired_reader_comparison"] = {
            "paired_attempted_count": len(paired),
            "selected_count": len(selected),
            "oracle": reader_metrics(paired, oracle),
            "retrieved": reader_metrics(paired, retrieved),
            "note": (
                "Same examples and prompt; only supplied snippet differs. "
                "Failed calls remain in paired denominators."
            ),
        }
    report["complete"] = report["retrieval"]["complete"] and all(
        result["complete"] for result in report["experiments"].values()
    )
    manifest["invocations"][-1].update(
        finished_at=report["updated_at"],
        elapsed_seconds=report["invocation_elapsed_seconds"],
        new_model_calls=new_calls,
        stopped_reason=stopped_reason,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    arguments = parser().parse_args()
    try:
        report = run(arguments)
    except (OSError, ValueError, httpx.HTTPError, KeyError, TypeError) as exc:
        raise SystemExit(f"OR-ShARC evaluation failed: {exc}") from exc
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
