import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.domain.models import ReturnCase, ReturnFacts
from app.evaluation.abcd import (
    FIELDS,
    SOURCE_REVISION,
    SOURCE_SHA256,
    VERSION,
    AbcdExample,
    ObservedModelExtractor,
    apply_reviewed_annotations,
    convert_conversation,
    prepare_abcd,
    run_evaluation,
    select_examples,
    summarize,
)
from app.extractors.base import ExtractorError
from app.extractors.hybrid import HybridExtractor
from app.extractors.ollama import OllamaExtractor


def conversation(convo_id: int = 17) -> dict[str, Any]:
    return {
        "convo_id": convo_id,
        "scenario": {
            "subflow": "return_size",
            "order": {"order_id": "1234567890", "packaging": "yes"},
            "product": {"names": ["adidas shoes"]},
        },
        "original": [
            ["customer", "Can I send these shoes back?"],
            ["agent", "Please give me the order ID."],
            ["customer", "1234567890"],
            ["agent", "The shoes are unopened and unused."],
            ["customer", "Thanks."],
        ],
        "delexed": [
            {"speaker": "customer", "text": "can i send these shoes back?"},
            {"speaker": "agent", "text": "please give me the order id."},
            {"speaker": "customer", "text": "<order_id>"},
            {"speaker": "agent", "text": "the shoes are unopened and unused."},
            {"speaker": "customer", "text": "thanks."},
        ],
    }


def example(**kwargs: Any) -> AbcdExample:
    defaults: dict[str, Any] = {
        "sample_id": "abcd:test:17:self_contained",
        "split": "test",
        "convo_id": 17,
        "task": "self_contained",
        "message": "They have never been worn.",
        "turn_index": None,
        "subflow": "return_size",
        "expected": {},
        "label_mask": dict.fromkeys(FIELDS, False),
        "evidence": {},
    }
    defaults.update(kwargs)
    return AbcdExample(**defaults)


def record(row: AbcdExample, **prediction: object) -> dict[str, Any]:
    return {
        "sample_id": row.sample_id,
        "convo_id": row.convo_id,
        "task": row.task,
        "prediction": prediction,
        "error": None,
        "latency_ms": 2,
        "ollama_usage": [],
    }


def test_converter_has_customer_evidence_and_no_latent_or_future_facts() -> None:
    rows = convert_conversation(conversation(), "test")
    full, first, order_reply, last = rows
    assert full.expected == {"order_id": "1234567890", "item_name": "shoes"}
    assert "unopened" not in full.message
    assert not full.label_mask["opened"]
    assert not full.label_mask["reason"]  # A latent return_size is not observed does_not_fit.
    assert not full.label_mask["intent"]
    assert first.current_case == {}  # The future order ID is never a contextual input.
    assert order_reply.pending_question == "order_id"
    assert order_reply.current_case == {"item_name": "shoes"}
    assert last.current_case["order_number"] == "1234567890"
    evidence = order_reply.evidence["order_id"][0]
    assert order_reply.message[evidence["start"] : evidence["end"]] == evidence["text"]


def test_scenario_value_not_observed_or_not_officially_delexed_is_masked() -> None:
    raw = conversation()
    raw["original"][2][1] = "I don't have my order number."
    rows = convert_conversation(raw, "test")
    assert not rows[0].label_mask["order_id"]
    raw["original"][2][1] = "1234567890"
    raw["delexed"][2]["text"] = "1234567890"
    assert not convert_conversation(raw, "test")[0].label_mask["order_id"]


def test_multi_product_mentions_are_not_silently_single_item_gold() -> None:
    raw = conversation()
    raw["scenario"]["product"]["names"] = ["adidas shoes", "nike shoes"]
    assert not convert_conversation(raw, "test")[0].label_mask["item_name"]


def test_false_conditions_are_scored_and_unreviewed_predictions_are_not_hallucinations() -> None:
    row = example(
        expected={"used": False, "order_id": None},
        label_mask={"used": True, "order_id": True},
        absence_audited=["order_id"],
    )
    result = summarize([row], [record(row, used=False, order_id="123", opened=True)])
    assert result["per_slot"]["used"]["tp"] == 1
    assert result["per_slot"]["used"]["f1"] == 1
    assert result["per_slot"]["order_id"]["fp"] == 1
    assert result["hallucinations"] == 1
    assert result["audited_absence_checks"] == 1
    assert result["unreviewed_predictions"] == 1
    assert result["labeled_exact_match"] == 0


def test_wrong_positive_is_both_false_positive_and_false_negative() -> None:
    row = example(expected={"order_id": "123"}, label_mask={"order_id": True})
    result = summarize([row], [record(row, order_id="ORD-123")])
    assert result["per_slot"]["order_id"]["fp"] == 1
    assert result["per_slot"]["order_id"]["fn"] == 1
    assert result["audited_hallucination_rate"] is None
    assert result["tokens"] is None


def test_wants_human_false_is_negative_class_but_false_conditions_are_facts() -> None:
    row = example(
        expected={"wants_human": False, "opened": False},
        label_mask={"wants_human": True, "opened": True},
        absence_audited=["wants_human"],
    )
    result = summarize([row], [record(row, wants_human=False, opened=False)])
    assert result["per_slot"]["wants_human"]["tn"] == 1
    assert result["per_slot"]["opened"]["tp"] == 1
    assert result["labeled_exact_match"] == 1
    assert result["hallucinations"] == 0


def test_conversation_sampling_and_counts_are_not_individual_turn_counts() -> None:
    rows = [row for index in range(4) for row in convert_conversation(conversation(index), "dev")]
    selected = select_examples(rows, task="all", limit=2, seed=3)
    assert len(selected) == 8
    assert len({row.convo_id for row in selected}) == 2
    assert [row.sample_id for row in selected] == [
        row.sample_id for row in select_examples(list(reversed(rows)), task="all", limit=2, seed=3)
    ]
    summary = summarize(selected, [record(row) for row in selected])
    assert summary["evaluated_conversations"] == 2
    assert summary["evaluated_examples"] == 8


def test_converter_preserves_native_splits_and_rejects_split_leakage(tmp_path: Path) -> None:
    source = tmp_path / "raw.json"
    source.write_text(
        json.dumps({split: [conversation(i)] for i, split in enumerate(("train", "dev", "test"))})
    )
    result = prepare_abcd(source, tmp_path / "prepared")
    assert [result["splits"][split]["conversations"] for split in ("train", "dev", "test")] == [
        1,
        1,
        1,
    ]
    source.write_text(json.dumps({split: [conversation()] for split in ("train", "dev", "test")}))
    with pytest.raises(ValueError, match="crosses splits"):
        prepare_abcd(source, tmp_path / "invalid")


def test_reviewed_overlay_requires_input_evidence_and_explicit_absence_audit(
    tmp_path: Path,
) -> None:
    row = example()
    annotation = {
        "projection_version": VERSION,
        "source_revision": SOURCE_REVISION,
        "source_sha256": SOURCE_SHA256,
        "reviewer": "unit test",
        "annotations": [
            {
                "sample_id": row.sample_id,
                "expected": {"used": False},
                "evidence": {"used": [{"text": "never been worn"}]},
            }
        ],
    }
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(annotation))
    apply_reviewed_annotations([row], path)
    assert row.expected["used"] is False and row.label_mask["used"]
    annotation["annotations"][0]["expected"] = {"opened": None}  # type: ignore[index]
    path.write_text(json.dumps(annotation))
    with pytest.raises(ValueError, match="absence audit"):
        apply_reviewed_annotations([row], path)


class CountingExtractor:
    def __init__(self, delay: float = 0, failure: bool = False) -> None:
        self.calls = 0
        self.delay = delay
        self.failure = failure

    async def extract(
        self, message: str, current_case: ReturnCase, pending_question: str | None
    ) -> ReturnFacts:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.failure:
            raise ExtractorError("fixture failure")
        return ReturnFacts(order_id="123")


@pytest.mark.asyncio
async def test_resume_does_not_requery_or_accept_changed_config(tmp_path: Path) -> None:
    row = example(expected={"order_id": "123"}, label_mask={"order_id": True})
    extractor = CountingExtractor()
    output = tmp_path / "predictions.jsonl"
    first = await run_evaluation([row], extractor, output, config={"provider": "fixture"})
    second = await run_evaluation(
        [row], extractor, output, config={"provider": "fixture"}, resume=True
    )
    assert first["complete"] and second["complete"] and extractor.calls == 1
    with pytest.raises(ValueError, match="does not match"):
        await run_evaluation([row], extractor, output, config={"provider": "changed"}, resume=True)


@pytest.mark.asyncio
async def test_time_budget_limits_inflight_call_and_reports_provider_errors(tmp_path: Path) -> None:
    rows = [
        example(sample_id=str(i), convo_id=i, expected={"used": False}, label_mask={"used": True})
        for i in range(2)
    ]
    summary = await run_evaluation(
        rows,
        CountingExtractor(delay=0.1),
        tmp_path / "p.jsonl",
        config={},
        time_budget_seconds=0.01,
    )
    assert not summary["complete"]
    assert summary["stopped_for_budget"]
    assert summary["overall"]["provider_errors"] == 1
    assert summary["overall"]["per_slot"]["used"]["fn"] == 1


@pytest.mark.asyncio
async def test_hybrid_absorbed_model_failure_is_still_observed(tmp_path: Path) -> None:
    model = ObservedModelExtractor(CountingExtractor(failure=True))
    hybrid = HybridExtractor(fallback=model)
    row = example()
    summary = await run_evaluation([row], hybrid, tmp_path / "hybrid.jsonl", config={})
    assert summary["overall"]["provider_errors"] == 0
    assert summary["overall"]["model_attempt_errors"] == 1
    assert summary["overall"]["model_calls"] == 1


@pytest.mark.asyncio
async def test_native_token_capture_uses_existing_ollama_extractor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"content": ReturnFacts(order_id="123").model_dump_json()},
                "prompt_eval_count": 37,
                "eval_count": 12,
            },
        )

    original = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    extractor = OllamaExtractor(base_url="http://localhost:11434/v1", model="fixture", retries=0)
    row = example(expected={"order_id": "123"}, label_mask={"order_id": True})
    summary = await run_evaluation([row], extractor, tmp_path / "p.jsonl", config={})
    assert summary["overall"]["tokens"] == {
        "input_tokens": 37,
        "output_tokens": 12,
        "measured_responses": 1,
        "source": "ollama_native_response",
    }
