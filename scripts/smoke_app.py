"""Exercise actual loopback HTTP services against a fresh synthetic demo database."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def require_local_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use a loopback HTTP origin, never a remote production service")
    return value.rstrip("/")


def run_smoke(base_url: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    observed_questions: dict[str, tuple[str, str]] = {}
    observed_submissions: list[str] = []
    started = perf_counter()
    with httpx.Client(
        base_url=require_local_origin(base_url), timeout=70, trust_env=False
    ) as client:

        def call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            response = client.request(method, path, json=payload)
            response.raise_for_status()
            body = dict(response.json())
            question = body.get("question")
            if question:
                observed_questions[question["question_id"]] = (
                    body["session_id"],
                    question["field"],
                )
            if (
                method == "POST"
                and payload
                and payload.get("session_id")
                and (path == "/api/v1/chat" or path.startswith("/api/v1/questions/"))
            ):
                observed_submissions.append(str(payload["session_id"]))
            return body

        def verify(name: str, condition: bool) -> None:
            checks.append({"name": name, "passed": condition})

        def chat(message: str, email: str, session: str | None = None) -> dict[str, Any]:
            return call(
                "POST",
                "/api/v1/chat",
                {
                    "session_id": session or str(uuid4()),
                    "customer_email": email,
                    "message": message,
                },
            )

        health = call("GET", "/health")
        if health.get("environment") != "local-demo":
            raise ValueError("Refusing writes: target must be started with scripts.local_demo")
        verify("liveness", health["status"] == "ok")
        verify("schema_readiness", call("GET", "/ready")["status"] == "ready")
        metrics = client.get("/metrics")
        verify("metrics", metrics.status_code == 200 and "http" in metrics.text)
        policy = call("POST", "/api/v1/policy/ask", {"question": "What is the return deadline?"})
        verify(
            "policy_window_citation",
            policy["status"] == "answered"
            and any(c["clause_id"] == "P-WINDOW" for c in policy["citations"]),
        )
        unknown = call("POST", "/api/v1/policy/ask", {"question": "What is tomorrow's weather?"})
        verify(
            "unsupported_policy_abstains",
            unknown["status"] == "no_match" and not unknown["citations"],
        )
        scoped = call(
            "POST",
            "/api/v1/policy/ask",
            {
                "question": "What is the return deadline?",
                "scope": "process",
            },
        )
        verify("metadata_scope_filter", all(c["scope"] == "process" for c in scoped["citations"]))
        specific = call("POST", "/api/v1/policy/ask", {"question": "Can I return ORD-1010?"})
        verify("policy_cannot_decide_order", specific["status"] == "case_specific_not_supported")

        session = str(uuid4())
        first = chat("Return ORD-1010 because the shirt doesn't fit.", "june@example.com", session)
        verify(
            "asks_missing_apparel_condition",
            (first.get("question") or {}).get("field") == "stained",
        )
        if first.get("question") is None:
            raise RuntimeError("Use a fresh demo DB: ORD-1010 is not available for the smoke flow")
        pending_id = first["question"]["question_id"]
        call("POST", "/api/v1/policy/ask", {"question": "Can I return used items?"})
        restored = call("GET", f"/api/v1/return-cases/{session}")
        verify(
            "policy_help_preserves_pending_question",
            restored["question"]["question_id"] == pending_id,
        )
        intruder = client.post(
            f"/api/v1/questions/{pending_id}/answer",
            json={
                "session_id": str(uuid4()),
                "selected_value": "no",
            },
        )
        verify("cross_session_answer_blocked", intruder.status_code == 403)
        second = chat(
            "I used it. It has no stains. The tags are attached. "
            "The tags are intact. It is not damaged.",
            "june@example.com",
            session,
        )
        verify(
            "worn_good_condition_advances_to_confirmation",
            second["decision"] == "eligible"
            and (second.get("question") or {}).get("field") == "confirm_return",
        )
        verify(
            "eligible_has_policy_basis",
            any(c["clause_id"] == "P-APPROVAL" for c in second["policy_evidence"]),
        )
        verify("no_rma_before_confirmation", second["return_request"] is None)
        if second.get("question") is None:
            raise RuntimeError(
                "Expected confirmation question before exercising demo return creation"
            )
        confirm_id = second["question"]["question_id"]
        confirmation = {"session_id": session, "selected_value": "confirm"}
        created = call("POST", f"/api/v1/questions/{confirm_id}/answer", confirmation)
        repeated = client.post(f"/api/v1/questions/{confirm_id}/answer", json=confirmation)
        verify(
            "confirmed_simulated_rma_created",
            created["state"] == "return_created" and created["return_request"] is not None,
        )
        verify("duplicate_confirmation_rejected", repeated.status_code == 409)
        idempotent = client.post(
            "/api/v1/returns",
            json={
                "session_id": session,
                "confirmation_question_id": confirm_id,
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        verify(
            "return_creation_is_idempotent",
            idempotent.status_code == 200
            and idempotent.json()["return_request"] == created["return_request"],
        )
        verify(
            "resume_returns_same_rma",
            call("GET", f"/api/v1/return-cases/{session}")["return_request"]
            == created["return_request"],
        )
        duplicate_case = chat(
            "Return ORD-1010 because the shirt doesn't fit. I never used it.", "june@example.com"
        )
        verify(
            "cross_session_duplicate_return_blocked",
            duplicate_case["reason_code"] == "ORDER_ALREADY_RETURNED"
            and duplicate_case["return_request"] is None,
        )

        for name, message, email, reason, clause in [
            ("final_sale", "Return ORD-1004", "dev@example.com", "FINAL_SALE", "P-FINAL-SALE"),
            ("expired", "Return ORD-1003", "cora@example.com", "OUTSIDE_RETURN_WINDOW", "P-WINDOW"),
            (
                "not_delivered",
                "Return ORD-1007",
                "gabe@example.com",
                "ORDER_NOT_DELIVERED",
                "P-DELIVERED",
            ),
            (
                "duplicate_order_return",
                "Return ORD-1008",
                "hana@example.com",
                "ORDER_ALREADY_RETURNED",
                "P-ALREADY-RETURNED",
            ),
            (
                "used",
                "Return ORD-1009 because I changed my mind. I used it.",
                "ivan@example.com",
                "USED_ITEM",
                "P-USAGE",
            ),
            (
                "defect",
                "Return ORD-1006 because it is broken.",
                "farah@example.com",
                "DEFECT_REQUIRES_REVIEW",
                "P-HUMAN-REVIEW",
            ),
        ]:
            result = chat(message, email)
            verify(name, result["reason_code"] == reason and result["return_request"] is None)
            verify(
                f"{name}_citation", any(c["clause_id"] == clause for c in result["policy_evidence"])
            )
        multi = chat("Return ORD-1005", "emma@example.com")
        verify(
            "multi_item_requires_selection", (multi.get("question") or {}).get("field") == "item_id"
        )
        denied = client.post(
            "/api/v1/chat",
            json={
                "session_id": str(uuid4()),
                "customer_email": "someone@example.com",
                "message": "Return ORD-1001",
            },
        )
        verify("wrong_owner_denied", denied.status_code in {403, 404})
    return {
        "kind": "actual HTTP application smoke on synthetic demo orders, not public benchmark",
        "base_url": base_url,
        "checks": checks,
        "check_count": len(checks),
        "passed_count": sum(row["passed"] for row in checks),
        "all_passed": all(row["passed"] for row in checks),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "resume_session_id": session,
        "created_return_id": created["return_request"]["id"],
        "observed_main_case": {
            "unique_questions": sum(sid == session for sid, _ in observed_questions.values()),
            "question_fields": [
                field for sid, field in observed_questions.values() if sid == session
            ],
            "user_submissions": observed_submissions.count(session),
            "note": "Observed for this synthetic flow only, not a user-study average.",
        },
        "limitations": [
            "SQLite demo, not PostgreSQL concurrency or deployment load testing.",
            "One deterministic flow, not a complete native tau2 benchmark score.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--allow-demo-writes", action="store_true")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    if not args.allow_demo_writes:
        parser.error(
            "Requires --allow-demo-writes and a fresh synthetic demo DB; creates a simulated RMA"
        )
    report = run_smoke(args.base_url)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
