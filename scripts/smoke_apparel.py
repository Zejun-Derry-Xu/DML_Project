"""Read-only by default; write smoke requires an explicitly disposable environment."""

import argparse
import json
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def smoke(
    base: str, expected_commit: str | None, write_demo: bool = False, require_model: bool = False
) -> dict[str, object]:
    checks = []
    session_id = None
    with httpx.Client(base_url=base.rstrip("/"), timeout=65) as client:
        health = client.get("/health")
        health.raise_for_status()
        ready = client.get("/ready")
        ready.raise_for_status()
        body = ready.json()
        assert body["workflow"] == "apparel"
        assert body["schema"] == "0004"
        if expected_commit:
            assert body["commit"] == expected_commit
        if require_model:
            assert write_demo and body["extraction_mode"] == "llm"
        checks.extend(["health", "ready_workflow_schema_commit"])
        policy = client.post(
            "/api/v1/policy/ask", json={"question": "What is the return deadline?"}
        )
        policy.raise_for_status()
        assert any(c["clause_id"] == "A-WINDOW" for c in policy.json()["citations"])
        checks.append("policy_window_citation")
        if write_demo:
            assert urlparse(base).hostname in {"127.0.0.1", "localhost"}, "Loopback only"
            assert health.json()["environment"] in {"local-demo", "ci-smoke"}, (
                "Disposable DB required"
            )
            accounts = client.get("/api/v1/demo/customers").json()
            alice = next(a for a in accounts if a["name"] == "Alice (fictional)")
            client.post(
                "/api/v1/demo/session", json={"customer_id": alice["id"]}
            ).raise_for_status()
            session_id = str(uuid4())
            response = client.post(
                "/api/v1/chat", json={"session_id": session_id, "message": "Return clothing"}
            )
            response.raise_for_status()
            case = response.json()
            assert not require_model or not case["degraded"]
            steps = 0
            while case.get("question") and steps < 12:
                q = case["question"]
                field = q["field"]
                if field == "reason_text":
                    response = client.post(
                        "/api/v1/chat", json={"session_id": session_id, "message": "too small"}
                    )
                else:
                    value = {
                        "order_id": "DEMO-1001",
                        "stained": "no",
                        "damaged": "no",
                        "tags_attached": "yes",
                        "tags_intact": "yes",
                        "confirm_return": "confirm",
                    }[field]
                    response = client.post(
                        f"/api/v1/questions/{q['question_id']}/answer",
                        json={
                            "session_id": session_id,
                            "selected_value": value,
                        },
                    )
                response.raise_for_status()
                case = response.json()
                assert not require_model or not case["degraded"]
                steps += 1
            assert case["state"] == "return_created", case
            checks.append("owned_guided_flow_to_simulated_rma")
        return {
            "checks": checks,
            "passed": len(checks),
            "write_demo": write_demo,
            "commit": body["commit"],
            "model_quality_tested": False,
            "model_transport_exercised": require_model,
            "model": body["model"],
            "session_id": session_id,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-commit")
    parser.add_argument("--write-demo", action="store_true")
    parser.add_argument("--require-model", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            smoke(args.base_url, args.expected_commit, args.write_demo, args.require_model),
            indent=2,
        )
    )
