import json

import httpx
import pytest

from app.config import Settings
from app.extractors.apparel_harness import HarnessExtractor, output_schema, source_spans
from app.extractors.apparel_llm import LLMFactExtractor, validate_extraction
from app.extractors.base import ExtractorError


def extractor(protocol="span_ids", capture=True):
    return HarnessExtractor(
        Settings(extraction_mode="llm", llm_provider="ollama"),
        protocol,
        capture_diagnostics=capture,
    )


def wire(field="damaged", value=False, state="stated", ids=None):
    return {
        "intent": "unclear",
        "intent_evidence_ids": [],
        "facts": [
            {
                "field": field,
                "value": value,
                "state": state,
                "evidence_ids": ["S1"] if ids is None else ids,
            }
        ],
    }


@pytest.mark.parametrize(
    "text",
    [
        "",
        "!!!",
        "No. Not damaged; tags attached.\nUnknown!",
        "No damage? If it were?",
        " é😀.\n no stains ",
        "a. " * 80,
    ],
)
def test_source_partition_is_lossless_and_bounded(text):
    spans = source_spans(text)
    assert "".join(s["text"] for s in spans) == text
    assert 1 <= len(spans) <= 16
    assert spans[0]["start"] == 0 and spans[-1]["end"] == len(text)
    assert all(text[s["start"] : s["end"]] == s["text"] for s in spans)


def test_false_preserved_and_original_text_recovered_not_generated():
    ex = extractor()
    result = ex.decode_response(json.dumps(wire()), "There isn't any damage.")
    assert result.facts[0].value is False
    assert result.facts[0].evidence == "There isn't any damage."
    assert ex.last_trace["resolved_candidates"]["facts"][0]["value"] is False


@pytest.mark.parametrize("ids", [["S99"], ["S1", "S1"], [1], "S1"])
def test_invalid_or_duplicate_ids_not_repaired(ids):
    with pytest.raises(ValueError, match="wire_evidence"):
        extractor().decode_response(json.dumps(wire(ids=ids)), "No damage.")


@pytest.mark.parametrize(
    "field,value,state",
    [
        ("damaged", "false", "stated"),
        ("stained", 0, "stated"),
        ("damaged", False, "uncertain"),
        ("invented", False, "stated"),
        ("condition_origin", "delivery", "stated"),
        ("tags_intact", None, "stated"),
    ],
)
def test_local_contract_rejects_invalid_types_and_states(field, value, state):
    with pytest.raises(ValueError, match="wire_"):
        extractor().decode_response(json.dumps(wire(field, value, state)), "No damage.")


def test_unknown_has_no_value_and_empty_not_mentioned_is_accepted():
    result = extractor().decode_response(
        json.dumps(wire(value=None, state="uncertain")), "I cannot tell."
    )
    assert result.facts[0].value is None
    result = extractor().decode_response(
        json.dumps(wire(value=None, state="not_mentioned", ids=[])), "Hello."
    )
    assert result.facts[0].state == "not_mentioned"
    result = extractor().decode_response(json.dumps(wire(ids=[])), "No damage.")
    assert not result.facts  # A stated value never gets evidence fabricated for it.


def test_contiguous_recovery_keeps_intervening_negation_and_unicode_offsets():
    result = extractor().decode_response(
        json.dumps(wire(ids=["S1", "S3"])), "😀 fine. Not torn. Tags attached."
    )
    assert result.facts[0].evidence == "😀 fine. Not torn. Tags attached."


def test_schema_prevents_free_field_names_and_string_booleans():
    schema = output_schema("typed", source_spans("No damage."))
    branches = schema["properties"]["facts"]["items"]["anyOf"]
    assert branches[0]["properties"]["value"]["type"] == "boolean"
    assert "damaged" in branches[0]["properties"]["field"]["enum"]
    assert branches[-1]["properties"]["value"]["type"] == "null"
    assert schema["additionalProperties"] is False


def test_typed_and_id_candidates_share_instructions_and_runtime_parameters():
    settings = Settings(extraction_mode="llm", llm_provider="ollama")
    a = HarnessExtractor(settings, "typed").build_payload("No stains.", {"target": "stained"})
    b = HarnessExtractor(settings, "span_ids").build_payload("No stains.", {"target": "stained"})
    assert a["options"] == b["options"]
    assert (
        a["messages"][0]["content"].split("\nEvidence:")[0]
        == b["messages"][0]["content"].split("\nEvidence:")[0]
    )
    payload = json.loads(b["messages"][1]["content"])
    assert payload["source_spans"][0]["text"] == "No stains."


def test_rejections_have_reason_codes_not_only_names():
    reasons = []
    body = {
        "intent": "unclear",
        "intent_evidence": "",
        "facts": [
            {
                "field": "damaged",
                "value": False,
                "state": "stated",
                "evidence": "No damage",
            }
        ],
    }
    result, rejected = validate_extraction(body, "No DAMAGE", diagnostics=reasons)
    assert not result.facts and rejected == ["damaged"]
    assert reasons == [{"field": "damaged", "reason": "evidence_not_exact_current_message"}]


@pytest.mark.asyncio
async def test_transport_records_before_after_without_retrying_semantic_failure(monkeypatch):
    calls = []
    original = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(wire(value="false"))},
                "done_reason": "stop",
                "eval_count": 20,
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    ex = extractor()
    with pytest.raises(ExtractorError):
        await ex.extract("No damage.", {})
    assert len(calls) == 1
    assert ex.last_trace["contract_error"] == "wire_value_state_type"
    assert ex.last_trace["stage"] == "wire_contract"
    assert ex.last_trace["parsed_candidates"]["facts"][0]["value"] == "false"
    assert ex.last_usage["eval_count"] == 20


def test_normal_extractor_does_not_capture_raw_candidate_text_by_default():
    ex = LLMFactExtractor(Settings())
    ex.decode_response(json.dumps({"intent": "unclear", "intent_evidence": "", "facts": []}), "Hi")
    assert "parsed_candidates" not in ex.last_trace
    assert "request" not in ex.last_trace
