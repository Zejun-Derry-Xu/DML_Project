"""Validated configuration is authoritative; retrieval never decides eligibility."""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import OrderItem, OrderSnapshot
from app.policy.corpus import PolicyClause, PolicyCorpus

VERSION = "apparel-1.0.0"
CONDITIONS = ("stained", "damaged", "tags_attached", "tags_intact")


class ApparelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    return_window_days: int = Field(ge=1, le=365)
    requires_delivered: bool
    allow_final_sale: bool
    required_conditions: dict[str, bool]
    origin_actions: dict[str, Literal["ineligible", "human_review"]]
    clauses: list[dict[str, Any]]

    @model_validator(mode="after")
    def valid_config(self) -> "ApparelPolicy":
        if set(self.required_conditions) != set(CONDITIONS):
            raise ValueError("Every supported resale condition must be configured")
        if set(self.origin_actions) != {"customer", "pre_existing", "unknown"}:
            raise ValueError("All origin actions must be explicit")
        ids = [c["id"] for c in self.clauses]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate policy clause")
        self.corpus()
        return self

    def corpus(self) -> PolicyCorpus:
        values = self.model_dump(exclude={"clauses"})
        rendered = [
            PolicyClause(
                id=c["id"],
                scope=c["scope"],
                content=c["content"].format_map(values),
                keywords=tuple(c["keywords"]),
                reason_codes=tuple(c["reason_codes"]),
            )
            for c in self.clauses
        ]
        return PolicyCorpus(self.version, "Simulated apparel return policy", tuple(rendered))


@lru_cache
def load_apparel_policy(version: str = VERSION) -> ApparelPolicy:
    if version != VERSION:
        raise ValueError("Unsupported apparel policy version")
    return ApparelPolicy.model_validate_json(
        (Path(__file__).parent / f"{version}.json").read_text()
    )


def precheck(
    order: OrderSnapshot, item: OrderItem, policy: ApparelPolicy, now: datetime | None = None
) -> str | None:
    if item.category != "apparel":
        return "NON_APPAREL"
    if policy.requires_delivered and (order.status != "delivered" or not order.delivered_at):
        return "ORDER_NOT_DELIVERED"
    if order.delivered_at:
        delivered = (
            order.delivered_at.replace(tzinfo=UTC)
            if order.delivered_at.tzinfo is None
            else order.delivered_at
        )
        current = now or datetime.now(UTC)
        if delivered > current:
            return "ORDER_NOT_DELIVERED"
        if current - delivered > timedelta(days=policy.return_window_days):
            return "OUTSIDE_RETURN_WINDOW"
    if item.final_sale and not policy.allow_final_sale:
        return "FINAL_SALE"
    if item.return_status:
        return "ORDER_ALREADY_RETURNED"
    return None
