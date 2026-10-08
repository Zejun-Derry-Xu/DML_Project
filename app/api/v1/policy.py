"""Read-only, retrieval-grounded explanations of the simulated MVP policy."""

from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.schemas import PolicyCitation
from app.config import get_settings
from app.policy.answering import (
    ExtractivePolicyGenerator,
    OllamaPolicyGenerator,
    PolicyGenerator,
    PolicyKnowledge,
)
from app.policy.corpus import load_policy
from app.policy.retrieval import (
    LexicalPolicyRetriever,
    OllamaEmbeddings,
    PolicyRetriever,
    QdrantPolicyRetriever,
)

router = APIRouter(prefix="/policy", tags=["policy"])


class PolicyQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    scope: Literal["eligibility", "intake", "process"] | None = None


class PolicyExplanation(BaseModel):
    status: str
    answer: str
    policy_version: str
    citations: list[PolicyCitation]
    retriever_used: str
    generator_used: str
    warning: str | None = None


@router.post("/ask", response_model=PolicyExplanation)
def ask_policy(payload: PolicyQuestion) -> PolicyExplanation:
    settings = get_settings()
    corpus = load_policy()
    with httpx.Client(timeout=15) as client:
        retriever: PolicyRetriever
        if settings.policy_retriever == "qdrant":
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
        generator: PolicyGenerator
        if settings.policy_generator == "ollama":
            generator = OllamaPolicyGenerator(
                client, url=settings.policy_ollama_url, model=settings.llm_model
            )
        else:
            generator = ExtractivePolicyGenerator()
        result = PolicyKnowledge(
            corpus,
            retriever,
            generator,
            retriever_name=settings.policy_retriever,
            generator_name=settings.policy_generator,
        ).answer(payload.question, scope=payload.scope)
    return PolicyExplanation(
        status=result.status,
        answer=result.answer,
        policy_version=corpus.version,
        citations=[
            PolicyCitation(
                clause_id=clause.id,
                policy_version=corpus.version,
                scope=clause.scope,
                content=clause.content,
            )
            for clause in result.citations
        ],
        retriever_used=result.retriever_used,
        generator_used=result.generator_used,
        warning=result.warning,
    )
