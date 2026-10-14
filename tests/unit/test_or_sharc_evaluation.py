import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.evaluation.or_sharc import (
    BM25Retriever,
    Checkpoint,
    Document,
    OllamaReader,
    OllamaVectorRetriever,
    by_seen,
    example_metadata,
    file_sha256,
    gold_decision,
    load_documents,
    load_examples,
    parse_example,
    reader_metrics,
    reader_payload,
    require_local_ollama,
    retrieval_metrics,
    seeded_sample,
    validate_corpus,
)
from scripts import evaluate_or_sharc


def row(identity: str = "a", answer: str = "Yes", seen: bool = True) -> dict[str, Any]:
    return {
        "utterance_id": identity,
        "tree_id": "shared-tree",
        "source_url": "https://target-only.invalid/SOURCE-SENTINEL",
        "question": "May I receive a scholarship?",
        "scenario": "I am enrolled.",
        "history": [{"follow_up_question": "Are you enrolled?", "follow_up_answer": "Yes"}],
        "gold_snippet_id": "A",
        "evidence": [{"follow_up_question": "EVIDENCE-SENTINEL", "follow_up_answer": "Yes"}],
        "answer": answer,
        "snippet_seen": seen,
        "snippet": "ORIGINAL-SNIPPET-SENTINEL",
    }


def successful(decision: str, citations: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "prediction": {
            "decision": decision,
            "answer": "A concise answer.",
            "evidence_ids": citations or ["A"],
        },
        "context_ids": ["A"],
        "latency_ms": 12,
        "prompt_tokens": 100,
        "completion_tokens": 20,
    }


def test_official_jsonl_schema_and_document_mapping(tmp_path: Path) -> None:
    split = tmp_path / "split.json"
    split.write_text(json.dumps(row()) + "\n\n" + json.dumps(row("b", "No", False)) + "\n")
    docs = tmp_path / "id2snippet.json"
    docs.write_text(json.dumps({"B": "Parking rules.", "A": "Scholarship rules."}))
    examples = load_examples(split)
    documents = load_documents(docs)
    validate_corpus(examples, documents)
    assert [document.id for document in documents] == ["A", "B"]
    assert examples[0].target.evidence[0]["follow_up_question"] == "EVIDENCE-SENTINEL"
    assert example_metadata(examples)["canonical_tree_group_count"] == 1
    assert example_metadata(examples)["seen_counts"] == {"seen": 1, "unseen": 1}


@pytest.mark.parametrize(
    "bad", [{"history": "bad"}, {"evidence": [], "scenario": None}, {"snippet_seen": "bad"}]
)
def test_jsonl_rejects_invalid_input_types(tmp_path: Path, bad: dict[str, Any]) -> None:
    split = tmp_path / "split.json"
    split.write_text(json.dumps({**row(), **bad}) + "\n")
    with pytest.raises(ValueError, match="split.json:1"):
        load_examples(split)


def test_duplicate_instances_and_missing_gold_documents_are_rejected(tmp_path: Path) -> None:
    split = tmp_path / "split.json"
    split.write_text(json.dumps(row()) + "\n" + json.dumps(row()) + "\n")
    with pytest.raises(ValueError, match="Duplicate utterance_id"):
        load_examples(split)
    with pytest.raises(ValueError, match="missing from corpus"):
        validate_corpus([parse_example(row())], [Document("B", "Unrelated.")])


def test_gold_and_extracted_evidence_cannot_leak_to_query_or_reader() -> None:
    example = parse_example(row(answer="ANSWER-SENTINEL?"))
    serialized = json.dumps(
        reader_payload(example.inputs, [Document("retrieved", "Retrieved rule.")])
    )
    query = example.inputs.retrieval_query()
    for forbidden in (
        "EVIDENCE-SENTINEL",
        "SOURCE-SENTINEL",
        "ORIGINAL-SNIPPET-SENTINEL",
        "ANSWER-SENTINEL",
        "shared-tree",
        "gold_snippet_id",
        "snippet_seen",
        "utterance_id",
    ):
        assert forbidden not in serialized
        assert forbidden not in query
    assert set(example.inputs.to_dict()) == {"question", "scenario", "history"}
    assert "Are you enrolled? Yes" in query


@pytest.mark.parametrize(
    ("answer", "expected"), [("Yes", "yes"), (" NO ", "no"), ("Are you a resident?", "inquire")]
)
def test_missing_facts_followup_label_is_inquire(answer: str, expected: str) -> None:
    assert gold_decision(answer) == expected


def test_no_silent_fourth_class_or_empty_target() -> None:
    with pytest.raises(ValueError, match="outside"):
        gold_decision("Irrelevant")
    with pytest.raises(ValueError, match="empty"):
        gold_decision(" ")


def test_bm25_is_deterministic_and_has_no_gold_candidate_filter() -> None:
    documents = [
        Document("B", "scholarship enrolled"),
        Document("A", "scholarship enrolled"),
        Document("C", "parking vehicle"),
    ]
    first = BM25Retriever(documents).search("scholarship enrolled", limit=3)
    second = BM25Retriever(list(reversed(documents))).search("scholarship enrolled", limit=3)
    assert first == second
    assert [hit.document.id for hit in first] == ["A", "B", "C"]
    assert first[0].score > 0 and first[-1].score == 0
    assert [hit.document.id for hit in BM25Retriever(documents).search("no_matching_token", 3)] == [
        "A",
        "B",
        "C",
    ]


def test_retrieval_mrr_is_full_rank_and_partial_errors_stay_in_denominator() -> None:
    examples = [parse_example(row("a")), parse_example(row("b")), parse_example(row("c"))]
    records = {
        "a": {"status": "ok", "retrieved_ids": ["B", "C", "D", "E", "F", "A"], "latency_ms": 1},
        "b": {"status": "timeout", "retrieved_ids": [], "latency_ms": 10},
    }
    metrics = retrieval_metrics(examples, records)
    assert metrics["metric_denominator"] == 3
    assert metrics["recall_at_5"] == 0
    assert metrics["mrr"] == pytest.approx(1 / 18)
    assert metrics["attempted_count"] == 2 and metrics["not_run_count"] == 1
    assert metrics["errors"] == {"timeout": 1} and not metrics["complete"]


def test_model_metrics_include_failure_and_missing_call_denominators() -> None:
    examples = [
        parse_example(row("a", "Yes")),
        parse_example(row("b", "No")),
        parse_example(row("c", "Is your residency permanent?", False)),
    ]
    records = {
        "a": successful("yes", ["A", "WRONG"]),
        "b": {"status": "timeout", "prediction": None, "latency_ms": 90},
    }
    metrics = reader_metrics(examples, records)
    assert metrics["decision_on_selected"]["accuracy"] == pytest.approx(1 / 3)
    assert metrics["decision_on_attempted"]["accuracy"] == 0.5
    assert metrics["decision_on_selected"]["macro_f1"] == pytest.approx(1 / 3)
    assert metrics["decision_on_selected"]["confusion"]["inquire"] == {"missing_or_error": 1}
    assert metrics["citation_doc_precision"] == 0.5
    assert metrics["citation_gold_doc_correctness_on_selected"] == pytest.approx(1 / 3)
    assert metrics["citation_outside_context_count"] == 1
    assert metrics["tokens"]["completion_tokens"] == {
        "total_measured": 20,
        "measured_call_count": 1,
        "unknown_call_count": 1,
    }
    assert metrics["errors"] == {"timeout": 1} and not metrics["complete"]
    assert by_seen(examples, records, reader=True)["unseen"]["not_run_count"] == 1


def test_incomplete_facts_prediction_is_evaluated_as_wrong_when_model_says_yes() -> None:
    example = parse_example(row(answer="Are you a resident?"))
    metrics = reader_metrics([example], {"a": successful("yes")})
    assert metrics["decision_on_selected"]["confusion"]["inquire"] == {"yes": 1}
    assert metrics["decision_on_selected"]["accuracy"] == 0
    # A correct gold document citation says nothing about this incorrect inference.
    assert metrics["citation_doc_precision"] == 1


def test_seeded_model_sample_ignores_labels_and_input_order() -> None:
    examples = [parse_example(row(str(index))) for index in range(20)]
    selected = [example.utterance_id for example in seeded_sample(examples, 7, 42)]
    changed = [
        parse_example(row(str(index), "Are you a resident?", False))
        for index in reversed(range(20))
    ]
    assert selected == [example.utterance_id for example in seeded_sample(changed, 7, 42)]
    assert selected != [example.utterance_id for example in seeded_sample(examples, 7, 99)]


def test_native_ollama_json_schema_prompt_and_tokens() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(successful("inquire")["prediction"])},
                "prompt_eval_count": 123,
                "eval_count": 31,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = OllamaReader(client).predict(
            parse_example(row()).inputs, [Document("A", "Residents enrolled qualify.")]
        )
    assert record["status"] == "ok"
    assert record["prompt_tokens"] == 123 and record["completion_tokens"] == 31
    assert calls[0]["think"] is False and calls[0]["stream"] is False
    assert calls[0]["format"]["additionalProperties"] is False
    assert "EVIDENCE-SENTINEL" not in json.dumps(calls)
    assert set(json.loads(calls[0]["messages"][1]["content"])["user"]) == {
        "question",
        "scenario",
        "history",
    }


@pytest.mark.parametrize(
    "content",
    [
        '{"decision":"maybe"}',
        '{"decision":"yes","answer":"OK","evidence_ids":["A"],"extra":"bad"}',
        '{"decision":"yes","answer":"OK","evidence_ids":["A","A"]}',
    ],
)
def test_invalid_reader_output_keeps_native_counts_and_raw_response(content: str) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"message": {"content": content}, "eval_count": 50}
            )
        )
    ) as client:
        record = OllamaReader(client).predict(parse_example(row()).inputs, [Document("A", "Rule.")])
    assert record["status"] == "schema_error" and record["prediction"] is None
    assert record["completion_tokens"] == 50
    assert record["raw_response"]["message"]["content"] == content


def test_timeout_is_observable_and_never_a_guess() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = OllamaReader(client).predict(parse_example(row()).inputs, [Document("A", "Rule.")])
    assert record["status"] == "timeout" and record["prediction"] is None
    assert record["completion_tokens"] is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://192.168.1.20:11434",
        "http://localhost:11434/api",
        "http://user:pass@localhost:11434",
        "http://localhost:11434?x=1",
    ],
)
def test_no_external_model_endpoint_is_permitted(url: str) -> None:
    with pytest.raises(ValueError, match="local HTTP"):
        require_local_ollama(url)


def test_local_vectors_exact_cosine_and_cache_validation(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        count = len(payload["input"])
        return httpx.Response(
            200, json={"embeddings": [[1, 0], [0, 1]] if count == 2 else [[0, 1]]}
        )

    docs = [Document("A", "rule a"), Document("B", "rule b")]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        retriever = OllamaVectorRetriever(
            docs,
            client,
            url="http://localhost:11434",
            model="embeddinggemma",
            cache_path=tmp_path / "vectors.json",
        )
        assert [hit.document.id for hit in retriever.search("query", 2)] == ["B", "A"]
        assert "task: search result | query:" in calls[-1]["input"][0]
        OllamaVectorRetriever(
            docs,
            client,
            url="http://localhost:11434",
            model="embeddinggemma",
            cache_path=tmp_path / "vectors.json",
        )
        assert len(calls) == 2
    with pytest.raises(ValueError, match="nonfinite"):
        OllamaVectorRetriever._validate_vectors([[float("nan")]], 1)


def test_checkpoint_resume_removes_only_truncated_final_record(tmp_path: Path) -> None:
    path = tmp_path / "predictions.jsonl"
    checkpoint = Checkpoint(path)
    checkpoint.append({"experiment": "reader_oracle", "utterance_id": "a", **successful("yes")})
    committed = path.read_bytes()
    path.write_bytes(committed + b'{"experiment":"reader')
    resumed = Checkpoint(path, resume=True)
    assert path.read_bytes() == committed
    assert set(resumed.experiment("reader_oracle")) == {"a"}
    with pytest.raises(ValueError, match="already contains"):
        resumed.append({"experiment": "reader_oracle", "utterance_id": "a"})
    with pytest.raises(ValueError, match="already exists"):
        Checkpoint(path)


def toy_sources(tmp_path: Path) -> Path:
    data = tmp_path / "sources"
    data.mkdir()
    (data / "id2snippet.json").write_text(
        json.dumps(
            {"A": "Enrolled residents can receive a scholarship.", "B": "Vehicle parking rules."}
        )
    )
    (data / "open_retrieval_sharc_dev.json").write_text(
        "\n".join(
            json.dumps(row(identity, "Yes" if identity == "a" else "No", identity == "a"))
            for identity in ["a", "b"]
        )
        + "\n"
    )
    files = [{"name": path.name, "sha256": file_sha256(path)} for path in data.iterdir()]
    (data / "manifest.json").write_text(
        json.dumps({"revision": "pinned-fixture", "license": "test-fixture", "files": files})
    )
    return data


def test_cli_all_experiments_fixed_sample_limit_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3:4b", "digest": "fixture-digest"}]}
            )
        assert request.url.path == "/api/chat"
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(successful("yes")["prediction"])},
                "prompt_eval_count": 80,
                "eval_count": 20,
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        evaluate_or_sharc.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    data = toy_sources(tmp_path)
    argv = [
        "--mode",
        "all",
        "--split",
        "dev",
        "--sample-size",
        "2",
        "--data-dir",
        str(data),
        "--run-dir",
        str(tmp_path / "run"),
        "--summary",
        str(tmp_path / "summary.json"),
    ]
    report = evaluate_or_sharc.run(evaluate_or_sharc.parser().parse_args([*argv, "--limit", "2"]))
    assert report["retrieval"]["complete"]
    assert report["new_model_calls"] == 2 and not report["complete"]
    assert report["paired_reader_comparison"]["paired_attempted_count"] == 1
    completed = evaluate_or_sharc.run(evaluate_or_sharc.parser().parse_args([*argv, "--resume"]))
    assert completed["complete"] and completed["new_model_calls"] == 4
    assert len(calls) == 6
    assert completed["paired_reader_comparison"]["paired_attempted_count"] == 2
    assert all(
        experiment["attempted_count"] == 2 for experiment in completed["experiments"].values()
    )
    changed = evaluate_or_sharc.parser().parse_args([*argv, "--resume", "--seed", "99"])
    with pytest.raises(ValueError, match="Cannot resume"):
        evaluate_or_sharc.run(changed)


def test_cli_retrieval_checks_pinned_source_hash_without_inference(tmp_path: Path) -> None:
    data = toy_sources(tmp_path)
    arguments = evaluate_or_sharc.parser().parse_args(
        [
            "--split",
            "dev",
            "--data-dir",
            str(data),
            "--run-dir",
            str(tmp_path / "run"),
            "--summary",
            str(tmp_path / "report.json"),
        ]
    )
    report = evaluate_or_sharc.run(arguments)
    assert report["complete"] and report["new_model_calls"] == 0
    assert report["retrieval"]["example_count"] == 2
    assert report["experiments"] == {}
    (data / "id2snippet.json").write_text(json.dumps({"A": "Changed rules."}))
    with pytest.raises(ValueError, match="checksum"):
        evaluate_or_sharc.run(arguments)
