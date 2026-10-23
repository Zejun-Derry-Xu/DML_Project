"""Create one future-format record ONLY in the isolated CI smoke database."""

import json
from uuid import uuid4

from app.config import get_settings
from app.db.models import ReturnCaseRecord
from app.db.session import SessionLocal
from scripts.seed_data import stable_id

if __name__ == "__main__":
    if get_settings().environment != "ci-smoke":
        raise RuntimeError("Compatibility fixture is restricted to the isolated CI database")
    session_id = uuid4()
    with SessionLocal.begin() as db:
        db.add(
            ReturnCaseRecord(
                session_id=session_id,
                customer_id=stable_id("demo-customer", "alice"),
                customer_email="demo-alice@example.invalid",
                workflow_version="future-readonly-test",
                policy_version="future-readonly-test",
                reason_text="new format must not be reinterpreted",
            )
        )
    print(json.dumps({"session_id": str(session_id)}))
