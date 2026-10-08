"""General policy explanations grounded in retrieved clauses."""

import re
from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.policy.corpus import PolicyClause, PolicyCorpus
from app.policy.retrieval import (
    LexicalPolicyRetriever,
    PolicyRetriever,
    PolicyUpstreamError,
)


@dataclass(frozen=True)
class PolicyAnswer:
    status: str
    answer: str
    citations: tuple[PolicyClause, ...]
    retriever_used: str
    generator_used: str
    warning: str | None = None


class PolicyGenerator(Protocol):
    def generate(self, question: str, clauses: list[PolicyClause]) -> str: ...


class _ModelAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=280)


class ExtractivePolicyGenerator:
    def generate(self, question: str, clauses: list[PolicyClause]) -> str:
        del question
        return "According to the MVP policy: " + " ".join(
            f"[{clause.id}] {clause.content}" for clause in clauses
        )


class OllamaPolicyGenerator:
    """Optional experimental wording; never used to decide or mutate a case."""

    def __init__(self, client: httpx.Client, *, url: str, model: str) -> None:
        self.client = client
        self.url = url.rstrip("/")
        self.model = model

    def generate(self, question: str, clauses: list[PolicyClause]) -> str:
        evidence = "\n".join(f"[{c.id}] {c.content}" for c in clauses)
        try:
            response = self.client.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "num_predict": 160},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Answer general questions about this simulated return policy "
                                "using only the supplied policy clauses. Do not decide whether "
                                "a particular order is eligible. Do not invent exceptions. "
                                "If the clauses do not answer the question, say you do not know. "
                                "Return one concise sentence with the supporting clause ID. "
                                "Do not include analysis or explain your instructions."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Question: {question}\nPolicy evidence:\n{evidence}",
                        },
                    ],
                    "format": _ModelAnswer.model_json_schema(),
                },
            )
            response.raise_for_status()
            content = _ModelAnswer.model_validate_json(response.json()["message"]["content"])
            answer = content.answer.strip()
            cited_ids = set(re.findall(r"\[(P-[A-Z-]+)\]", answer))
            if not cited_ids or not cited_ids <= {clause.id for clause in clauses}:
                raise ValueError("Missing or unsupported policy citation")
            return answer
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise PolicyUpstreamError("Policy wording model unavailable") from exc


class PolicyKnowledge:
    def __init__(
        self, corpus: PolicyCorpus, retriever: PolicyRetriever,
        generator: PolicyGenerator, *, retriever_name: str, generator_name: str,
    ) -> None:
        self.corpus = corpus
        self.retriever = retriever
        self.generator = generator
        self.retriever_name = retriever_name
        self.generator_name = generator_name

    def answer(self, question: str, *, scope: str | None = None) -> PolicyAnswer:
        if re.search(r"\bORD[- ]?[A-Z0-9]+\b", question, flags=re.IGNORECASE):
            return PolicyAnswer(
                status="case_specific_not_supported",
                answer=(
                    "Use the return-case flow for a specific order; "
                    "this endpoint only explains general policy."
                ),
                citations=(),
                retriever_used=self.retriever_name,
                generator_used=self.generator_name,
            )
        warnings: list[str] = []
        retriever_used = self.retriever_name
        generator_used = self.generator_name
        try:
            clauses = self.retriever.search(question, scope=scope)
        except PolicyUpstreamError:
            clauses = LexicalPolicyRetriever(self.corpus).search(question, scope=scope)
            retriever_used = "lexical_fallback"
            warnings.append("Semantic retrieval unavailable; used lexical retrieval.")
        if not clauses:
            return PolicyAnswer(
                status="no_match",
                answer="I could not find a policy clause that answers this question.",
                citations=(),
                retriever_used=retriever_used,
                generator_used="none",
                warning=" ".join(warnings) or None,
            )
        try:
            answer = self.generator.generate(question, clauses)
        except PolicyUpstreamError:
            answer = ExtractivePolicyGenerator().generate(question, clauses)
            generator_used = "extractive_fallback"
            warnings.append("Answer model unavailable; quoted retrieved policy clauses instead.")
        return PolicyAnswer(
            status="answered",
            answer=answer,
            citations=tuple(clauses),
            retriever_used=retriever_used,
            generator_used=generator_used,
            warning=" ".join(warnings) or None,
        )
