"""The one authoritative document used for policy explanations in this spike."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).parent / "data" / "mvp-1.0.0.json"


@dataclass(frozen=True)
class PolicyClause:
    id: str
    scope: str
    content: str
    keywords: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PolicyCorpus:
    version: str
    title: str
    clauses: tuple[PolicyClause, ...]

    def by_id(self, clause_id: str) -> PolicyClause | None:
        return next((clause for clause in self.clauses if clause.id == clause_id), None)


@lru_cache(maxsize=1)
def load_policy() -> PolicyCorpus:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    clauses = tuple(
        PolicyClause(
            id=row["id"],
            scope=row["scope"],
            content=row["content"],
            keywords=tuple(row["keywords"]),
            reason_codes=tuple(row["reason_codes"]),
        )
        for row in payload["clauses"]
    )
    if len({clause.id for clause in clauses}) != len(clauses):
        raise ValueError("Policy clause IDs must be unique")
    return PolicyCorpus(version=payload["version"], title=payload["title"], clauses=clauses)
