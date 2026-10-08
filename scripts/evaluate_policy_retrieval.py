"""Tiny, transparent retrieval smoke evaluation; not a representative benchmark."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import httpx

from app.config import get_settings
from app.policy.corpus import load_policy
from app.policy.retrieval import (
    LexicalPolicyRetriever,
    OllamaEmbeddings,
    PolicyRetriever,
    QdrantPolicyRetriever,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "policy_retrieval_questions.json"
)


def evaluate(retriever: PolicyRetriever) -> dict[str, object]:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        started = perf_counter()
        retrieved = retriever.search(case["question"], limit=3)
        elapsed_ms = (perf_counter() - started) * 1000
        actual = [clause.id for clause in retrieved]
        expected = case["expected_ids"]
        success = (
            all(clause_id in actual for clause_id in expected)
            if expected else not actual
        )
        results.append(
            {
                "question": case["question"],
                "expected_ids": expected,
                "retrieved_ids": actual,
                "pass_at_3_or_abstain": success,
                "latency_ms": round(elapsed_ms, 3),
            }
        )
    return {
        "case_count": len(results),
        "passed": sum(row["pass_at_3_or_abstain"] for row in results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("lexical", "qdrant"), default="lexical")
    args = parser.parse_args()
    settings = get_settings()
    corpus = load_policy()
    with httpx.Client(timeout=30) as client:
        retriever: PolicyRetriever
        if args.backend == "qdrant":
            retriever = QdrantPolicyRetriever(
                corpus,
                client,
                OllamaEmbeddings(
                    client, settings.policy_ollama_url, settings.policy_embedding_model
                ),
                url=settings.policy_qdrant_url,
                collection=settings.policy_qdrant_collection,
                api_key=settings.policy_qdrant_api_key,
                min_score=settings.policy_min_vector_score,
            )
        else:
            retriever = LexicalPolicyRetriever(corpus)
        report = evaluate(retriever)
    print(json.dumps({"backend": args.backend, **report}, indent=2))


if __name__ == "__main__":
    main()
