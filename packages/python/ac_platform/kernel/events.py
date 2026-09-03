from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class EventCategory(StrEnum):
    DOMAIN_FACT = "domain_fact"
    AUDIT = "audit"
    ANALYTICS = "analytics"
    OPERATIONAL = "operational"
    COST = "cost"


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    name: str
    category: EventCategory
    aggregate_type: str
    aggregate_id: UUID
    tenant_id: UUID | None
    payload: dict[str, Any]
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.name or not self.aggregate_type:
            raise ValueError("Event name and aggregate type are required.")
        if self.category is EventCategory.AUDIT and self.tenant_id is None:
            raise ValueError("Audit events require an explicit tenant boundary.")
