"""Small, explicit synthetic supplement for gold JSON -> policy decision and citations."""

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import BaseModel, Field

from app.domain.models import OrderItem, OrderSnapshot, ReturnReason
from app.domain.policy_engine import evaluate_return
from app.policy.corpus import PolicyClause, load_policy
from app.policy.retrieval import LexicalPolicyRetriever

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "policy_decision_cases.json"


class DecisionAnswer(BaseModel):
    decision: Literal["eligible", "ineligible", "need_more_information", "human_review"]
    answer: str = Field(min_length=1, max_length=500)
    citations: list[str]


def facts_for(row: dict[str, Any]) -> dict[str, Any]:
    facts = {
        "status": "delivered",
        "days": 2,
        "final_sale": False,
        "return_status": None,
        "reason": "does_not_fit",
        "used": False,
        "damaged": False,
        "wants_human": False,
    }
    facts.update({key: value for key, value in row.items() if key in facts})
    return facts


def evidence_query(facts: dict[str, Any]) -> str:
    # Construct from facts only; expected labels/reason codes are never passed here.
    terms = ["return delivered delivery days window"]
    if facts["final_sale"]:
        terms.append("final sale")
    if facts["return_status"]:
        terms.append("duplicate existing return")
    if facts["reason"] is None:
        terms.append("reason why")
    if facts["reason"] in {"defective", "wrong_item"} or facts["damaged"]:
        terms.append("defect wrong item damaged human")
    if facts["wants_human"]:
        terms.append("human")
    terms.append("used unused use status")
    terms.append("eligible approve confirmation")
    return " ".join(terms)


def rule_decision(facts: dict[str, Any]) -> tuple[str, str]:
    item = OrderItem(
        id=uuid5(NAMESPACE_URL, "eval:item"),
        product_name="Evaluation item",
        price=10,
        final_sale=facts["final_sale"],
        return_status=facts["return_status"],
    )
    order = OrderSnapshot(
        id=uuid5(NAMESPACE_URL, "eval:order"),
        order_number="ORD-EVAL",
        customer_email="eval@example.com",
        status=facts["status"],
        ordered_at=NOW - timedelta(days=120),
        delivered_at=None if facts["days"] is None else NOW - timedelta(days=facts["days"]),
        items=[item],
    )
    result = evaluate_return(
        order,
        item,
        reason=ReturnReason(facts["reason"]) if facts["reason"] else None,
        used=facts["used"],
        damaged=facts["damaged"],
        wants_human=facts["wants_human"],
        now=NOW,
    )
    return result.decision.value, result.reason_code.value


def model_payload(
    facts: dict[str, Any], evidence: list[PolicyClause], model: str
) -> dict[str, Any]:
    verified_facts = {
        "order_status": facts["status"],
        "days_since_delivery": facts["days"],
        "item_is_final_sale": facts["final_sale"],
        "has_existing_return_request": bool(facts["return_status"]),
        "customer_return_reason": facts["reason"],
        "item_used": facts["used"],
        "customer_reports_damage": facts["damaged"],
        "customer_requests_human": facts["wants_human"],
    }
    return {
        "model": model,
        "stream": False,
        "think": False,
        "format": DecisionAnswer.model_json_schema(),
        "options": {"temperature": 0, "num_predict": 220},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Evaluate a simulated return from verified order and customer facts. "
                    "Use only provided policy clauses. Choose eligible, ineligible, "
                    "need_more_information, or human_review. Unknown facts are null, not false. "
                    "Cite only IDs from the evidence, and give a short explanation. "
                    "If the supplied evidence is insufficient, choose need_more_information."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "verified_facts": verified_facts,
                        "policy_evidence": [{"id": c.id, "content": c.content} for c in evidence],
                    }
                ),
            },
        ],
    }


def evaluate(
    *,
    mode: str,
    run_path: Path,
    model: str = "qwen3:4b",
    base_url: str = "http://127.0.0.1:11434",
    timeout: float = 60,
    time_budget: float = 600,
    resume: bool = False,
) -> dict[str, Any]:
    rows = json.loads(FIXTURE.read_text())
    fingerprint = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    config = {
        "evaluator_version": "return-policy-v2",
        "mode": mode,
        "model": model,
        "policy_version": load_policy().version,
        "fixture_sha256": fingerprint,
        "policy_sha256": hashlib.sha256(
            json.dumps([(clause.id, clause.content) for clause in load_policy().clauses]).encode()
        ).hexdigest(),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "base_url": base_url,
    }
    predictions: list[dict[str, Any]] = []
    if run_path.exists() and not resume:
        raise ValueError("Output already exists; choose a new run path or use --resume")
    if resume and run_path.exists():
        stored = json.loads(run_path.read_text())
        if stored["config"] != config:
            raise ValueError("Resume configuration differs from stored run")
        predictions = stored["predictions"]
    complete_ids = {entry["id"] for entry in predictions}
    started_run = perf_counter()
    corpus = load_policy()
    retriever = LexicalPolicyRetriever(corpus)
    with httpx.Client(timeout=timeout) as client:
        for row in rows:
            if row["id"] in complete_ids:
                continue
            if perf_counter() - started_run >= time_budget:
                break
            facts = facts_for(row)
            evidence = (
                list(corpus.clauses)
                if mode == "llm_full_policy"
                else retriever.search(evidence_query(facts), limit=3)
            )
            started = perf_counter()
            prediction: dict[str, Any] = {
                "id": row["id"],
                "expected_decision": row["expected_decision"],
                "expected_clause": row["expected_clause"],
            }
            if mode in {"rules", "hybrid_rag"}:
                decision, reason = rule_decision(facts)
                if mode == "rules":
                    evidence = retriever.search("", reason_code=reason, limit=9)
                citations = [clause.id for clause in evidence if reason in clause.reason_codes]
                prediction.update(decision=decision, citations=citations, tokens=0, status="scored")
            else:
                try:
                    response = client.post(
                        f"{base_url.rstrip('/')}/api/chat",
                        json=model_payload(facts, evidence, model),
                    )
                    response.raise_for_status()
                    body = response.json()
                    answer = DecisionAnswer.model_validate_json(body["message"]["content"])
                    if not set(answer.citations) <= {clause.id for clause in evidence}:
                        raise ValueError("Model cited an unavailable clause")
                    prediction.update(
                        decision=answer.decision,
                        citations=answer.citations,
                        status="scored",
                        tokens=body.get("prompt_eval_count", 0) + body.get("eval_count", 0),
                        input_tokens=body.get("prompt_eval_count"),
                        output_tokens=body.get("eval_count"),
                        answer=answer.answer,
                    )
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    prediction.update(
                        decision=None,
                        citations=[],
                        status="provider_error",
                        error_type=type(exc).__name__,
                        tokens=None,
                    )
            prediction["latency_ms"] = round((perf_counter() - started) * 1000, 3)
            prediction["retrieved_ids"] = [clause.id for clause in evidence]
            predictions.append(prediction)
            run_path.parent.mkdir(parents=True, exist_ok=True)
            run_path.write_text(
                json.dumps({"config": config, "predictions": predictions}, indent=2)
            )
    count = len(predictions)
    labels = ("eligible", "ineligible", "need_more_information", "human_review")
    f1_scores = []
    for label in labels:
        tp = sum(p["decision"] == label == p["expected_decision"] for p in predictions)
        fp = sum(p["decision"] == label != p["expected_decision"] for p in predictions)
        fn = sum(p["expected_decision"] == label != p["decision"] for p in predictions)
        f1_scores.append(2 * tp / max(2 * tp + fp + fn, 1))
    denied = [p for p in predictions if p["expected_decision"] != "eligible"]
    latencies = sorted(float(p["latency_ms"]) for p in predictions)
    return {
        "dataset_kind": "hand-authored synthetic policy boundary supplement",
        "config": config,
        "requested_count": len(rows),
        "attempted_count": count,
        "completed_all": count == len(rows),
        "decision_accuracy": sum(p["decision"] == p["expected_decision"] for p in predictions)
        / max(count, 1),
        "decision_macro_f1": sum(f1_scores) / len(labels),
        "false_approval_rate": sum(p["decision"] == "eligible" for p in denied)
        / max(len(denied), 1),
        "gold_clause_citation_rate": sum(
            p["expected_clause"] in p["citations"] for p in predictions
        )
        / max(count, 1),
        "retrieval_recall_at_3": (
            sum(p["expected_clause"] in p["retrieved_ids"] for p in predictions) / max(count, 1)
            if mode in {"llm_rag", "hybrid_rag"}
            else None
        ),
        "provider_errors": sum(p["status"] != "scored" for p in predictions),
        "measured_tokens": sum(p["tokens"] or 0 for p in predictions),
        "latency_ms": {
            "p50": latencies[max(0, math.ceil(len(latencies) * 0.5) - 1)] if latencies else None,
            "p95": latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)] if latencies else None,
        },
        "limitations": [
            "Small synthetic supplement, not a public dataset benchmark.",
            "Citation ID match does not establish textual entailment.",
            "Rules and hybrid_rag share the deterministic decision engine.",
        ],
    }
