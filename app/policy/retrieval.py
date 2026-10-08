"""Swappable lexical baseline and Ollama/Qdrant semantic policy retrieval."""

import re
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.policy.corpus import PolicyClause, PolicyCorpus

_STOP_WORDS = {
    "a", "an", "and", "are", "can", "do", "for", "how", "i", "is", "it", "my",
    "of", "on", "or", "policy", "return", "the", "to", "what", "when", "will",
}


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold())) - _STOP_WORDS


class PolicyRetriever(Protocol):
    def search(
        self, question: str, *, scope: str | None = None, reason_code: str | None = None,
        limit: int = 3,
    ) -> list[PolicyClause]: ...


class LexicalPolicyRetriever:
    def __init__(self, corpus: PolicyCorpus) -> None:
        self.corpus = corpus

    def search(
        self, question: str, *, scope: str | None = None, reason_code: str | None = None,
        limit: int = 3,
    ) -> list[PolicyClause]:
        question_terms = _terms(question)
        ranked: list[tuple[int, PolicyClause]] = []
        for clause in self.corpus.clauses:
            if scope is not None and clause.scope != scope:
                continue
            reason_match = reason_code is not None and reason_code in clause.reason_codes
            if reason_code is not None and not reason_match:
                continue
            text_score = len(question_terms & _terms(clause.content))
            keyword_score = sum(
                3 if keyword in question.casefold() else 0
                for keyword in clause.keywords
                if " " in keyword
            ) + sum(
                2 for keyword in clause.keywords
                if " " not in keyword and keyword in question_terms
            )
            # One generic content word is not enough evidence for a policy match.
            if not reason_match and keyword_score == 0 and text_score < 2:
                continue
            score = text_score + keyword_score + (100 if reason_match else 0)
            if score > 0:
                ranked.append((score, clause))
        ranked.sort(key=lambda entry: (-entry[0], entry[1].id))
        return [clause for _, clause in ranked[:limit]]


class PolicyUpstreamError(Exception):
    """An optional retrieval or generation dependency is unavailable."""


class OllamaEmbeddings:
    def __init__(self, client: httpx.Client, url: str, model: str) -> None:
        self.client = client
        self.url = url.rstrip("/")
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = self.client.post(
                f"{self.url}/api/embed", json={"model": self.model, "input": list(texts)}
            )
            response.raise_for_status()
            embeddings = response.json()["embeddings"]
            if len(embeddings) != len(texts) or not all(embeddings):
                raise ValueError("Embedding count or dimension mismatch")
            return [[float(value) for value in vector] for vector in embeddings]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise PolicyUpstreamError("Embedding service unavailable") from exc


class QdrantPolicyRetriever:
    def __init__(
        self, corpus: PolicyCorpus, client: httpx.Client, embeddings: OllamaEmbeddings,
        *, url: str, collection: str, api_key: str = "", min_score: float = 0.45,
    ) -> None:
        self.corpus = corpus
        self.client = client
        self.embeddings = embeddings
        self.url = url.rstrip("/")
        self.collection = collection
        self.headers = {"api-key": api_key} if api_key else {}
        self.min_score = min_score

    def index(self) -> None:
        """Explicit, repeatable indexing; never run automatically on an API request."""
        vectors = self.embeddings.embed([clause.content for clause in self.corpus.clauses])
        if len({len(vector) for vector in vectors}) != 1:
            raise ValueError("Policy embeddings have inconsistent dimensions")
        points = [
            {
                "id": str(uuid5(NAMESPACE_URL, f"{self.corpus.version}:{clause.id}")),
                "vector": vector,
                "payload": {
                    "clause_id": clause.id,
                    "policy_version": self.corpus.version,
                    "scope": clause.scope,
                    "content": clause.content,
                },
            }
            for clause, vector in zip(self.corpus.clauses, vectors, strict=True)
        ]
        collection_url = f"{self.url}/collections/{self.collection}"
        indexed_fields: set[str] = set()
        try:
            existing = self.client.get(collection_url, headers=self.headers)
            if existing.status_code == 404:
                self._put(
                    f"/collections/{self.collection}",
                    {"vectors": {"size": len(vectors[0]), "distance": "Cosine"}},
                )
            else:
                existing.raise_for_status()
                collection = existing.json()["result"]
                configured_size = collection["config"]["params"]["vectors"]["size"]
                if configured_size != len(vectors[0]):
                    raise ValueError("Existing Qdrant collection has a different vector size")
                indexed_fields = set(collection.get("payload_schema", {}))
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            raise PolicyUpstreamError("Qdrant collection unavailable") from exc
        for field in ("policy_version", "scope"):
            if field not in indexed_fields:
                self._put(
                    f"/collections/{self.collection}/index?wait=true",
                    {"field_name": field, "field_schema": "keyword"},
                )
        self._put(f"/collections/{self.collection}/points?wait=true", {"points": points})

    def search(
        self, question: str, *, scope: str | None = None, reason_code: str | None = None,
        limit: int = 3,
    ) -> list[PolicyClause]:
        if reason_code is not None:
            # Reason codes are application facts, not semantic guesses.
            return LexicalPolicyRetriever(self.corpus).search(
                question, scope=scope, reason_code=reason_code, limit=limit
            )
        conditions: list[dict[str, object]] = [
            {"key": "policy_version", "match": {"value": self.corpus.version}}
        ]
        if scope is not None:
            conditions.append({"key": "scope", "match": {"value": scope}})
        vector = self.embeddings.embed([question])[0]
        result = self._post(
            f"/collections/{self.collection}/points/query",
            {
                "query": vector,
                "filter": {"must": conditions},
                "limit": limit,
                "score_threshold": self.min_score,
                "with_payload": True,
            },
        )
        try:
            points = result["result"]["points"]
            clause_ids = [point["payload"]["clause_id"] for point in points]
            clauses = [self.corpus.by_id(clause_id) for clause_id in clause_ids]
            return [
                clause for clause in clauses
                if clause is not None and (scope is None or clause.scope == scope)
            ]
        except (KeyError, TypeError) as exc:
            raise PolicyUpstreamError("Malformed Qdrant result") from exc

    def _put(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._request("PUT", path, payload)

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, object]) -> dict[str, Any]:
        try:
            response = self.client.request(
                method, f"{self.url}{path}", json=payload, headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Non-object Qdrant response")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise PolicyUpstreamError("Qdrant unavailable") from exc
