from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import Base, database_is_ready
from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import ExtractorError
from app.extractors.hybrid import HybridExtractor
from app.services.conversation_service import ConversationService
from scripts.local_demo import demo_environment
from scripts.smoke_app import require_local_origin


def test_negative_boolean_facts_are_observable_not_discarded() -> None:
    assert ConversationService._present_fields(
        ReturnFacts(used=False, opened=False, damaged=False)
    ) == ["used", "opened", "damaged"]


def test_readiness_rejects_reachable_but_unmigrated_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as session, pytest.raises(SQLAlchemyError, match="tables"):
        database_is_ready(session)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert database_is_ready(session)
    engine.dispose()


def test_demo_overrides_external_services_without_altering_parent_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://unrelated")
    monkeypatch.setenv("POLICY_RETRIEVER", "qdrant")
    monkeypatch.setenv("LLM_API_KEY", "example-not-a-real-secret")
    env = demo_environment(Path("/tmp/returnflow-demo.db"), "rules", 8111, 5222)
    assert env["DATABASE_URL"] == f"sqlite+pysqlite:///{Path('/tmp/returnflow-demo.db').resolve()}"
    assert env["POLICY_RETRIEVER"] == "lexical"
    assert env["POLICY_GENERATOR"] == "extractive"
    assert env["LLM_API_KEY"] == ""
    assert env["RETURNFLOW_API_ORIGIN"] == "http://127.0.0.1:8111"


@pytest.mark.asyncio
async def test_hybrid_records_outage_without_discarding_known_rules():
    from unittest.mock import AsyncMock
    from uuid import uuid4

    provider = AsyncMock()
    provider.extract.side_effect = ExtractorError("unavailable")
    extractor = HybridExtractor(provider)
    facts = await extractor.extract("Return ORD-1010", ReturnCase(session_id=uuid4()), None)
    assert facts.order_id == "ORD-1010"
    assert facts.used is None
    assert extractor.last_path == "model_error_rules_fallback"


@pytest.mark.parametrize("url", ["https://localhost", "http://example.com", "http://x@localhost"])
def test_live_smoke_cannot_target_external_or_credentialed_origins(url):
    with pytest.raises(ValueError, match="loopback"):
        require_local_origin(url)
