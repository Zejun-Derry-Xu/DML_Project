"""Explicitly index the versioned MVP policy into the optional Qdrant backend."""

import httpx

from app.config import get_settings
from app.policy.corpus import load_policy
from app.policy.retrieval import OllamaEmbeddings, QdrantPolicyRetriever


def main() -> None:
    settings = get_settings()
    corpus = load_policy()
    with httpx.Client(timeout=60) as client:
        retriever = QdrantPolicyRetriever(
            corpus,
            client,
            OllamaEmbeddings(client, settings.policy_ollama_url, settings.policy_embedding_model),
            url=settings.policy_qdrant_url,
            collection=settings.policy_qdrant_collection,
            api_key=settings.policy_qdrant_api_key,
        )
        retriever.index()
    print(f"Indexed {len(corpus.clauses)} clauses from {corpus.version}.")


if __name__ == "__main__":
    main()
