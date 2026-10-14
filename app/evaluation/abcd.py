"""Evidence-constrained ABCD projection and masked ReturnFacts evaluation.

ABCD is not a ReturnFacts dataset. Its scenario/subflow is never a model input;
only customer spans grounded in the official annotations become automatic gold.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, cast
from unittest.mock import patch
from uuid import UUID

import httpx

from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import FactExtractor
from app.extractors.hybrid import HybridExtractor

FIELDS = ("intent", "order_id", "item_name", "reason", "used", "opened", "damaged", "wants_human")
SPLITS = ("train", "dev", "test")
VERSION = "abcd-returnfacts-v1"
SOURCE_REVISION = "6b8700ce67c6b37b062dd7a60abc76d7ef832a97"
SOURCE_SHA256 = "2bdf53ac359543dcdc38d55bc6513e78df120363f8f44870716e909f4606de15"
FactValue = str | bool | None
Task = Literal["self_contained", "contextual"]


@dataclass
class AbcdExample:
    sample_id: str
    split: str
    convo_id: int | str
    task: Task
    message: str
    turn_index: int | None
    subflow: str
    expected: dict[str, FactValue]
    label_mask: dict[str, bool]
    evidence: dict[str, list[dict[str, Any]]]
    current_case: dict[str, str] = field(default_factory=dict)
    pending_question: str | None = None
    absence_audited: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _span(text: str, value: str) -> re.Match[str] | None:
    """Match an official value, allowing only orthographic separators."""
    words = re.split(r"[\s_-]+", value.strip())
    if not words or not all(words):
        return None
    expression = r"(?<!\w)" + r"[\s_-]+".join(re.escape(w) for w in words) + r"(?!\w)"
    return re.search(expression, text, flags=re.IGNORECASE)


def _product_names(scenario: dict[str, Any]) -> list[str]:
    names = scenario.get("product", {}).get("names", [])
    return [name for name in names if isinstance(name, str) and name.strip()]


def _ground_turn(
    text: str, delexed_text: str, scenario: dict[str, Any], index: int
) -> tuple[dict[str, FactValue], dict[str, list[dict[str, Any]]]]:
    labels: dict[str, FactValue] = {}
    evidence: dict[str, list[dict[str, Any]]] = {}
    order_id = scenario.get("order", {}).get("order_id")
    if isinstance(order_id, str) and "<order_id>" in delexed_text:
        match = _span(text, order_id)
        if match is not None:
            labels["order_id"] = order_id
            evidence["order_id"] = [
                {
                    "turn_index": index,
                    "start": match.start(),
                    "end": match.end(),
                    "text": match.group(),
                    "basis": "official_customer_order_id_placeholder",
                }
            ]

    # Catalog membership disambiguates identity; the gold value remains an observed
    # surface span, never an unspoken brand or product supplied by the scenario.
    product_matches: dict[str, re.Match[str]] = {}
    for name in _product_names(scenario):
        match = _span(text, name)
        if match is None:
            product_type = re.split(r"[\s_]+", name.strip())[-1]
            match = _span(text, product_type)
        if match is not None:
            product_matches[name] = match
    if len(product_matches) == 1:
        name, match = next(iter(product_matches.items()))
        labels["item_name"] = match.group()
        evidence["item_name"] = [
            {
                "turn_index": index,
                "start": match.start(),
                "end": match.end(),
                "text": match.group(),
                "basis": "official_catalog_exact_customer_span",
                "catalog_identity": name,
            }
        ]
    return labels, evidence


def _pending(agent_text: str) -> str | None:
    """Map only an observed prior agent request into the app's supported context."""
    text = agent_text.casefold()
    if re.search(r"\border\s*(?:id|number)\b", text) and re.search(
        r"\b(?:what|provide|give|have|need|tell|share)\b", text
    ):
        return "order_id"
    if re.search(r"\b(?:which|what)\b.*\b(?:item|product)\b", text):
        return "item_id"
    return None


def convert_conversation(conversation: dict[str, Any], split: str) -> list[AbcdExample]:
    original = conversation["original"]
    delexed = conversation.get("delexed", [])
    scenario = conversation.get("scenario", {})
    convo_id = conversation["convo_id"]
    subflow = str(scenario.get("subflow", ""))
    current_case: dict[str, str] = {}
    agent_text = ""
    customers: list[str] = []
    contextual: list[AbcdExample] = []
    all_values: dict[str, list[FactValue]] = defaultdict(list)
    all_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for index, turn in enumerate(original):
        speaker, text = turn
        if speaker == "agent":
            agent_text = str(text)
            continue
        if speaker != "customer":
            continue
        text = str(text)
        customers.append(text)
        aligned = index < len(delexed) and delexed[index].get("speaker") == "customer"
        delexed_text = str(delexed[index].get("text", "")) if aligned else ""
        labels, evidence = _ground_turn(text, delexed_text, scenario, index)
        contextual.append(
            AbcdExample(
                sample_id=f"abcd:{split}:{convo_id}:contextual:{index}",
                split=split,
                convo_id=convo_id,
                task="contextual",
                message=text,
                turn_index=index,
                subflow=subflow,
                expected=labels,
                label_mask={slot: slot in labels for slot in FIELDS},
                evidence=evidence,
                current_case=dict(current_case),
                pending_question=_pending(agent_text),
            )
        )
        for slot, value in labels.items():
            all_values[slot].append(value)
            all_evidence[slot].extend(evidence[slot])
            if isinstance(value, str):
                current_case["order_number" if slot == "order_id" else slot] = value

    full_labels: dict[str, FactValue] = {}
    for slot, values in all_values.items():
        normalized = {normalize_value(slot, value) for value in values}
        identities = {entry.get("catalog_identity") for entry in all_evidence[slot]}
        if len(normalized) == 1 or (slot == "item_name" and len(identities) == 1):
            full_labels[slot] = max(values, key=lambda value: len(str(value)))
    full = AbcdExample(
        sample_id=f"abcd:{split}:{convo_id}:self_contained",
        split=split,
        convo_id=convo_id,
        task="self_contained",
        message="\n".join(customers),
        turn_index=None,
        subflow=subflow,
        expected=full_labels,
        label_mask={slot: slot in full_labels for slot in FIELDS},
        evidence={slot: all_evidence[slot] for slot in full_labels},
    )
    return [full, *contextual]


def normalize_value(slot: str, value: FactValue) -> FactValue:
    if isinstance(value, str):
        value = " ".join(value.casefold().split())
        if slot == "item_name":
            value = re.sub(r"[\s_-]+", " ", value).strip(" .!?,")
    return value


def _read_source(source: Path) -> dict[str, Any]:
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            return cast(dict[str, Any], json.load(handle))
    return cast(dict[str, Any], json.loads(source.read_text(encoding="utf-8")))


def prepare_abcd(source: Path, output_dir: Path) -> dict[str, Any]:
    raw = _read_source(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    statistics: dict[str, Any] = {}
    seen: set[int | str] = set()
    for split in SPLITS:
        conversations = raw[split]
        counts: Counter[str] = Counter()
        coverage: Counter[str] = Counter()
        with (output_dir / f"{split}.jsonl").open("w", encoding="utf-8") as handle:
            for conversation in conversations:
                convo_id = conversation["convo_id"]
                if convo_id in seen:
                    raise ValueError(f"Conversation {convo_id} crosses splits or is duplicated")
                seen.add(convo_id)
                if str(conversation.get("scenario", {}).get("subflow", "")).startswith("return_"):
                    counts["direct_return_conversations"] += 1
                for row in convert_conversation(conversation, split):
                    counts[row.task] += 1
                    coverage.update(f"{row.task}:{slot}" for slot in row.expected)
                    handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
        statistics[split] = {
            "conversations": len(conversations),
            "tasks": dict(counts),
            "annotated_fields": dict(coverage),
        }
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {
        "projection_version": VERSION,
        "source_revision": SOURCE_REVISION if source_sha256 == SOURCE_SHA256 else None,
        "source_is_official_pinned_artifact": source_sha256 == SOURCE_SHA256,
        "source_sha256": source_sha256,
        "source": "https://github.com/asappresearch/abcd",
        "splits": statistics,
        "label_policy": "positive_customer_span_only; all_unaudited_fields_masked",
        "unsupported_automatic_slots": [
            slot for slot in FIELDS if slot not in {"order_id", "item_name"}
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_examples(path: Path) -> list[AbcdExample]:
    return [AbcdExample(**json.loads(line)) for line in path.read_text().splitlines() if line]


def apply_reviewed_annotations(examples: list[AbcdExample], path: Path) -> None:
    """Apply a separately reviewed overlay; positive labels must cite input spans.

    An omitted key is unreviewed. A reviewed null labels audited absence only
    when explicitly listed in absence_audited. The overlay is not an extractor.
    """
    overlay = json.loads(path.read_text())
    if (
        overlay.get("projection_version") != VERSION
        or overlay.get("source_revision") != SOURCE_REVISION
        or overlay.get("source_sha256") != SOURCE_SHA256
    ):
        raise ValueError("Reviewed annotation source/projection version does not match")
    if not overlay.get("reviewer"):
        raise ValueError("Reviewed annotation overlays must identify their reviewer")
    rows = {row.sample_id: row for row in examples}
    seen: set[str] = set()
    for annotation in overlay["annotations"]:
        sample_id = annotation["sample_id"]
        if sample_id in seen or sample_id not in rows:
            raise ValueError(f"Duplicate or unknown reviewed sample: {sample_id}")
        seen.add(sample_id)
        row = rows[sample_id]
        expected = annotation["expected"]
        if not set(expected).issubset(FIELDS):
            raise ValueError(f"Unsupported reviewed fields in {sample_id}")
        ReturnFacts.model_validate(expected)
        evidence = annotation.get("evidence", {})
        audited = annotation.get("absence_audited", [])
        if not set(audited).issubset(expected):
            raise ValueError("Absence audits require explicit reviewed expected fields")
        for slot, value in expected.items():
            absent = (
                value is None
                or (slot == "intent" and value == "unclear")
                or (slot == "wants_human" and value is False)
            )
            if absent:
                if slot not in audited:
                    raise ValueError(
                        f"Reviewed absent value lacks an absence audit: {sample_id}:{slot}"
                    )
            elif not evidence.get(slot) or any(
                not entry.get("text") or entry["text"] not in row.message
                for entry in evidence[slot]
            ):
                raise ValueError(f"Reviewed value lacks customer evidence: {sample_id}:{slot}")
            row.expected[slot] = value
            row.label_mask[slot] = True
            row.evidence[slot] = evidence.get(slot, [])
        row.absence_audited = sorted(set(row.absence_audited) | set(audited))


def select_examples(
    examples: list[AbcdExample],
    *,
    task: str = "self_contained",
    seed: int = 42,
    limit: int | None = None,
    return_only: bool = False,
) -> list[AbcdExample]:
    selected = [
        row
        for row in examples
        if (task == "all" or row.task == task)
        and (not return_only or row.subflow.startswith("return_"))
    ]
    conversations = sorted(
        {row.convo_id for row in selected},
        key=lambda convo_id: hashlib.sha256(f"{seed}:{convo_id}".encode()).hexdigest(),
    )
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        conversations = conversations[:limit]
    rank = {convo_id: index for index, convo_id in enumerate(conversations)}
    return sorted(
        (row for row in selected if row.convo_id in rank),
        key=lambda row: (rank[row.convo_id], row.sample_id),
    )


def _present(slot: str, value: FactValue) -> bool:
    # False is a meaningful used/opened/damaged fact. The schema's default
    # wants_human=False is instead the negative human-request class.
    return value is not None and not (
        (slot == "intent" and value == "unclear") or (slot == "wants_human" and value is False)
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    return (
        round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3) if values else None
    )


def summarize(examples: list[AbcdExample], records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = {row.sample_id: row for row in examples}
    counters = {slot: Counter[str]() for slot in FIELDS}
    latencies: list[float] = []
    exact = scored = errors = hallucinations = absence_checks = 0
    attempted_model_calls = 0
    model_attempt_errors = 0
    unreviewed_predictions = 0
    evaluated_conversations: set[int | str] = set()
    scored_conversations: set[int | str] = set()
    exact_by_conversation: dict[int | str, bool] = {}
    token_counts: Counter[str] = Counter()
    measured_responses = 0
    for record in records:
        row = rows[record["sample_id"]]
        evaluated_conversations.add(row.convo_id)
        failed = record.get("error") is not None
        actual = record.get("prediction") or {}
        errors += failed
        attempted_model_calls += int(record.get("model_calls", 0))
        model_attempt_errors += len(record.get("model_attempt_errors", []))
        latencies.append(float(record["latency_ms"]))
        annotated = [slot for slot in FIELDS if row.label_mask.get(slot, False)]
        matched = not failed
        for slot in FIELDS:
            predicted = cast(FactValue, actual.get(slot))
            counter = counters[slot]
            if slot not in annotated:
                unreviewed_predictions += _present(slot, predicted) and not (
                    slot == "wants_human" and predicted is False
                )
                continue
            counter["annotated"] += 1
            gold = row.expected[slot]
            equals = not failed and normalize_value(slot, predicted) == normalize_value(slot, gold)
            matched = matched and equals
            counter["correct"] += equals
            if _present(slot, gold):
                counter["positive"] += 1
                counter["tp" if equals else "fn"] += 1
                if not equals and _present(slot, predicted):
                    counter["fp"] += 1
            elif _present(slot, predicted):
                counter["fp"] += 1
            elif not failed:
                counter["tn"] += 1
            if slot in row.absence_audited:
                absent = (
                    gold is None
                    or (slot == "intent" and gold == "unclear")
                    or (slot == "wants_human" and gold is False)
                )
                if not absent:
                    raise ValueError(f"Audited absence conflicts with {row.sample_id}:{slot}")
                absence_checks += 1
                hallucinations += predicted is not None and not (
                    (slot == "intent" and predicted == "unclear")
                    or (slot == "wants_human" and predicted is False)
                )
        if annotated:
            scored += 1
            exact += matched
            scored_conversations.add(row.convo_id)
            exact_by_conversation[row.convo_id] = (
                exact_by_conversation.get(row.convo_id, True) and matched
            )
        for usage in record.get("ollama_usage", []):
            if "prompt_eval_count" in usage and "eval_count" in usage:
                measured_responses += 1
                token_counts["input_tokens"] += int(usage["prompt_eval_count"])
                token_counts["output_tokens"] += int(usage["eval_count"])
    per_slot: dict[str, Any] = {}
    total = Counter[str]()
    for slot, counter in counters.items():
        tp, fp, fn = counter["tp"], counter["fp"], counter["fn"]
        total.update(counter)
        denominator = 2 * tp + fp + fn
        per_slot[slot] = {
            **{
                key: counter[key]
                for key in ("annotated", "positive", "correct", "tp", "fp", "fn", "tn")
            },
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "f1": round(2 * tp / denominator, 4) if denominator else None,
            "field_coverage": round(counter["annotated"] / len(records), 4) if records else 0,
        }
    denominator = 2 * total["tp"] + total["fp"] + total["fn"]
    return {
        "selected_examples": len(examples),
        "evaluated_examples": len(records),
        "selected_conversations": len({row.convo_id for row in examples}),
        "evaluated_conversations": len(evaluated_conversations),
        "scored_examples": scored,
        "scored_conversations": len(scored_conversations),
        "unscored_examples": len(records) - scored,
        "unscored_conversations": len(evaluated_conversations - scored_conversations),
        "zero_label_policy": "evaluated for latency/errors; excluded from accuracy denominators",
        "labeled_exact_match": round(exact / scored, 4) if scored else None,
        "conversation_labeled_exact_match": round(
            sum(exact_by_conversation.values()) / len(scored_conversations), 4
        )
        if scored_conversations
        else None,
        "labeled_slot_accuracy": round(total["correct"] / total["annotated"], 4)
        if total["annotated"]
        else None,
        "micro_f1": round(2 * total["tp"] / denominator, 4) if denominator else None,
        "per_slot": per_slot,
        "unannotated_slots": [slot for slot in FIELDS if counters[slot]["annotated"] == 0],
        "provider_errors": errors,
        "model_calls": attempted_model_calls,
        "model_attempt_errors": model_attempt_errors,
        "audited_absence_checks": absence_checks,
        "hallucinations": hallucinations,
        "audited_hallucination_rate": round(hallucinations / absence_checks, 4)
        if absence_checks
        else None,
        "unreviewed_predictions": unreviewed_predictions,
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "tokens": {
            **dict(token_counts),
            "measured_responses": measured_responses,
            "source": "ollama_native_response",
        }
        if measured_responses
        else None,
    }


class OllamaUsageCapture:
    """Observe native response counters without altering the tested extractor."""

    def __init__(self) -> None:
        self.usage: list[dict[str, int]] = []
        self.original_client = httpx.AsyncClient

    async def response_hook(self, response: httpx.Response) -> None:
        await response.aread()
        try:
            payload = response.json()
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        keys = ("prompt_eval_count", "eval_count", "total_duration", "load_duration")
        observed = {key: payload[key] for key in keys if isinstance(payload.get(key), int)}
        if observed:
            self.usage.append(observed)

    def client_factory(self, *args: Any, **kwargs: Any) -> httpx.AsyncClient:
        hooks = kwargs.setdefault("event_hooks", {})
        hooks.setdefault("response", []).append(self.response_hook)
        return self.original_client(*args, **kwargs)


class ObservedModelExtractor:
    """Retain fallback failures that the production hybrid legitimately absorbs."""

    def __init__(self, extractor: FactExtractor) -> None:
        self.extractor = extractor
        self.calls = 0
        self.errors: list[str] = []

    async def extract(
        self, message: str, current_case: ReturnCase, pending_question: str | None
    ) -> ReturnFacts:
        self.calls += 1
        try:
            return await self.extractor.extract(message, current_case, pending_question)
        except Exception as exc:
            self.errors.append(f"{type(exc).__name__}: {exc}")
            raise


def _observed_model(extractor: FactExtractor) -> ObservedModelExtractor | None:
    if isinstance(extractor, ObservedModelExtractor):
        return extractor
    if isinstance(extractor, HybridExtractor) and isinstance(
        extractor.fallback, ObservedModelExtractor
    ):
        return extractor.fallback
    return None


async def run_evaluation(
    examples: list[AbcdExample],
    extractor: FactExtractor,
    output: Path,
    *,
    config: dict[str, Any],
    resume: bool = False,
    time_budget_seconds: float | None = None,
    request_timeout_seconds: float = 30,
) -> dict[str, Any]:
    selected_ids = [row.sample_id for row in examples]
    run_id = hashlib.sha256(
        json.dumps({"config": config, "selected_ids": selected_ids}, sort_keys=True).encode()
    ).hexdigest()
    records: list[dict[str, Any]] = []
    if output.exists():
        if not resume:
            raise ValueError(f"Output already exists; use --resume or a new path: {output}")
        for line in output.read_text().splitlines():
            if line:
                record = json.loads(line)
                if record.get("run_id") != run_id:
                    raise ValueError("Resume configuration/input selection does not match")
                records.append(record)
    done = {record["sample_id"] for record in records}
    if len(done) != len(records) or not done.issubset(set(selected_ids)):
        raise ValueError("Duplicate or foreign sample IDs in resumed output")
    output.parent.mkdir(parents=True, exist_ok=True)
    observed_model = _observed_model(extractor)
    started_run = perf_counter()
    stopped_for_budget = False
    with output.open("a", encoding="utf-8") as handle:
        for row in examples:
            if row.sample_id in done:
                continue
            remaining = (
                None
                if time_budget_seconds is None
                else time_budget_seconds - (perf_counter() - started_run)
            )
            if remaining is not None and remaining <= 0:
                stopped_for_budget = True
                break
            timeout = (
                min(request_timeout_seconds, remaining)
                if remaining is not None
                else request_timeout_seconds
            )
            capture = OllamaUsageCapture()
            earlier_calls = observed_model.calls if observed_model else 0
            earlier_errors = len(observed_model.errors) if observed_model else 0
            started = perf_counter()
            prediction: dict[str, Any] | None = None
            error: str | None = None
            try:
                case = ReturnCase(session_id=UUID(int=0), **row.current_case)
                with patch("app.extractors.ollama.httpx.AsyncClient", capture.client_factory):
                    facts = await asyncio.wait_for(
                        extractor.extract(row.message, case, row.pending_question), timeout=timeout
                    )
                prediction = facts.model_dump(mode="json")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            record = {
                "run_id": run_id,
                "sample_id": row.sample_id,
                "convo_id": row.convo_id,
                "task": row.task,
                "prediction": prediction,
                "error": error,
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "ollama_usage": capture.usage,
                "model_calls": observed_model.calls - earlier_calls if observed_model else 0,
                "model_attempt_errors": observed_model.errors[earlier_errors:]
                if observed_model
                else [],
            }
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            records.append(record)
    summary = {
        "projection_version": VERSION,
        "run_id": run_id,
        "config": config,
        "complete": len(records) == len(examples),
        "stopped_for_budget": stopped_for_budget,
        "elapsed_this_invocation_seconds": round(perf_counter() - started_run, 3),
        "overall": summarize(examples, records),
    }
    for task in ("self_contained", "contextual"):
        task_rows = [row for row in examples if row.task == task]
        if task_rows:
            summary[task] = summarize(
                task_rows, [record for record in records if record["task"] == task]
            )
    return_rows = [row for row in examples if row.subflow.startswith("return_")]
    return_ids = {row.sample_id for row in return_rows}
    if return_rows:
        summary["direct_return_subflows"] = summarize(
            return_rows, [record for record in records if record["sample_id"] in return_ids]
        )
    return summary
