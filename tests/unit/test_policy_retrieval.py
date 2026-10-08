import httpx
import pytest

from app.domain.reason_codes import ReasonCode
from app.policy.answering import (
    ExtractivePolicyGenerator,
    OllamaPolicyGenerator,
    PolicyKnowledge,
)
from app.policy.corpus import load_policy
from app.policy.retrieval import (
    LexicalPolicyRetriever,
    OllamaEmbeddings,
    PolicyUpstreamError,
    QdrantPolicyRetriever,
)
from scripts.evaluate_policy_retrieval import evaluate


def test_policy_corpus_covers_decision_codes() -> None:
    corpus = load_policy()
    covered = {code for clause in corpus.clauses for code in clause.reason_codes}
    assert {
        ReasonCode.ORDER_NOT_DELIVERED,
        ReasonCode.OUTSIDE_RETURN_WINDOW,
        ReasonCode.FINAL_SALE,
        ReasonCode.ORDER_ALREADY_RETURNED,
        ReasonCode.USED_ITEM,
        ReasonCode.DEFECT_REQUIRES_REVIEW,
        ReasonCode.ELIGIBLE,
    } <= covered


@pytest.mark.parametrize(
    ("question", "clause_id"),
    [
        ("How many days after delivery can I return an item?", "P-WINDOW"),
        ("Can final sale merchandise be returned?", "P-FINAL-SALE"),
        ("What if the item was used?", "P-USAGE"),
        ("Do I need to confirm a return request?", "P-APPROVAL"),
    ],
)
def test_lexical_baseline_retrieves_expected_clause(question: str, clause_id: str) -> None:
    result = LexicalPolicyRetriever(load_policy()).search(question)
    assert result and result[0].id == clause_id


def test_scope_filter_and_abstention() -> None:
    retriever = LexicalPolicyRetriever(load_policy())
    assert retriever.search("How many days after delivery?", scope="process") == []
    assert retriever.search("What is the weather tomorrow?") == []


def test_general_answer_cites_document_but_refuses_order_specific_decision() -> None:
    corpus = load_policy()
    knowledge = PolicyKnowledge(
        corpus, LexicalPolicyRetriever(corpus), ExtractivePolicyGenerator(),
        retriever_name="lexical", generator_name="extractive",
    )
    answer = knowledge.answer("Can a final sale item be returned?")
    assert answer.status == "answered"
    assert answer.citations[0].id == "P-FINAL-SALE"
    assert "[P-FINAL-SALE]" in answer.answer
    specific = knowledge.answer("Can I return ORD-1010?")
    assert specific.status == "case_specific_not_supported"
    assert not specific.citations


def test_qdrant_query_uses_version_and_scope_metadata_filters() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})
        if request.url.path.endswith("/points/query"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [
                            {"score": 0.8, "payload": {"clause_id": "P-WINDOW"}}
                        ]
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        retriever = QdrantPolicyRetriever(
            load_policy(), client, OllamaEmbeddings(client, "http://ollama", "embeddinggemma"),
            url="http://qdrant", collection="test_policy",
        )
        result = retriever.search("What is the return window?", scope="eligibility")
    assert [clause.id for clause in result] == ["P-WINDOW"]
    assert calls[1].url.path == "/collections/test_policy/points/query"
    assert b'"policy_version"' in calls[1].content
    assert b'"eligibility"' in calls[1].content


def test_semantic_upstream_failure_falls_back_to_lexical() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    corpus = load_policy()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        retriever = QdrantPolicyRetriever(
            corpus, client, OllamaEmbeddings(client, "http://ollama", "embeddinggemma"),
            url="http://qdrant", collection="test_policy",
        )
        result = PolicyKnowledge(
            corpus, retriever, ExtractivePolicyGenerator(),
            retriever_name="qdrant", generator_name="extractive",
        ).answer("Can I return a final sale item?")
    assert result.status == "answered"
    assert result.retriever_used == "lexical_fallback"
    assert result.citations[0].id == "P-FINAL-SALE"


def test_ollama_generation_receives_only_retrieved_evidence() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": "[P-WINDOW] Within 30 days."}})

    clause = load_policy().by_id("P-WINDOW")
    assert clause is not None
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        answer = OllamaPolicyGenerator(client, url="http://ollama", model="qwen3:4b").generate(
            "What is the window?", [clause]
        )
    assert "[P-WINDOW]" in answer
    assert b"P-WINDOW" in requests[0].content
    assert b'"think":false' in requests[0].content


def test_embedding_errors_are_explicit() -> None:
    with (
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as c,
        pytest.raises(PolicyUpstreamError),
    ):
        OllamaEmbeddings(c, "http://ollama", "embeddinggemma").embed(["test"])


def test_small_retrieval_fixture() -> None:
    report = evaluate(LexicalPolicyRetriever(load_policy()))
    assert report["case_count"] == 12
    assert report["passed"] == 12


def test_qdrant_index_is_explicit_and_stores_version_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/embed":
            inputs = request.read().decode()
            assert '"input"' in inputs
            return httpx.Response(
                200,
                json={"embeddings": [[0.1, 0.2] for _ in load_policy().clauses]},
            )
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json={"status": "ok"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        QdrantPolicyRetriever(
            load_policy(), client, OllamaEmbeddings(client, "http://ollama", "embeddinggemma"),
            url="http://qdrant", collection="test_policy",
        ).index()
    assert [request.method for request in requests] == ["POST", "GET", "PUT", "PUT", "PUT", "PUT"]
    assert b'"policy_version":"mvp-1.0.0"' in requests[-1].content
    assert b'"size":2' in requests[2].content
