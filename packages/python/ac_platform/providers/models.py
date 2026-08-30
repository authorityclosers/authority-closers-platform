"""SQLAlchemy 2 model for verified provider-event deduplication."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from ac_platform.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-side defaults."""

    return datetime.now(UTC)


class ProviderInboxStatus(StrEnum):
    """Processing lifecycle for an accepted provider event."""

    RECEIVED = "received"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    PROCESSED = "processed"
    DEAD_LETTER = "dead_letter"
    FAILED = "retry_wait"


class ProviderInbox(Base):
    """One provider event accepted once before any webhook side effect runs."""

    __tablename__ = "provider_inbox"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_event_id",
            name="uq_provider_inbox_provider_event",
        ),
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="provider_nonblank",
        ),
        CheckConstraint(
            "length(trim(external_event_id)) > 0",
            name="external_event_id_nonblank",
        ),
        CheckConstraint(
            "status IN ('received', 'processing', 'retry_wait', 'processed', 'dead_letter')",
            name="status",
        ),
        CheckConstraint(
            "length(payload_digest) = 64",
            name="payload_digest_length",
        ),
        CheckConstraint(
            "processing_attempts >= 0 AND max_processing_attempts >= 1 "
            "AND processing_attempts <= max_processing_attempts",
            name="processing_attempt_bounds",
        ),
        CheckConstraint(
            "(status = 'processing' AND processing_lease_token IS NOT NULL "
            "AND processing_lease_until IS NOT NULL) OR "
            "(status <> 'processing' AND processing_lease_token IS NULL "
            "AND processing_lease_until IS NULL)",
            name="processing_lease_state_consistent",
        ),
        CheckConstraint(
            "(status = 'processed' AND processed_at IS NOT NULL) OR "
            "(status <> 'processed' AND processed_at IS NULL)",
            name="processed_state_consistent",
        ),
        CheckConstraint(
            "(status = 'dead_letter' AND dead_lettered_at IS NOT NULL) OR "
            "(status <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name="dead_letter_state_consistent",
        ),
        CheckConstraint(
            "(status IN ('retry_wait', 'dead_letter') AND last_error IS NOT NULL) OR "
            "(status NOT IN ('retry_wait', 'dead_letter') AND last_error IS NULL)",
            name="failure_state_consistent",
        ),
        CheckConstraint(
            "status NOT IN ('retry_wait', 'dead_letter') OR "
            "(last_error IS NOT NULL AND length(trim(last_error)) > 0)",
            name="failure_evidence_nonblank",
        ),
        CheckConstraint(
            "verified_body_digest IS NULL OR length(verified_body_digest) = 64",
            name="verified_body_digest_length",
        ),
        Index("ix_provider_inbox_status_available", "status", "available_at"),
        Index("ix_provider_inbox_tenant", "tenant_id", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_provider_inbox_tenant_id_tenants"),
        nullable=True,
    )
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    verified_body_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProviderInboxStatus.RECEIVED.value,
        server_default=ProviderInboxStatus.RECEIVED.value,
    )
    processing_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_processing_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    processing_lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    processing_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    @property
    def event_id(self) -> str:
        """Provider-neutral alias for the external dedupe identifier."""

        return self.external_event_id


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()
    return str(value)


def canonical_provider_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize a webhook payload deterministically before deduplication."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def provider_payload_digest(payload: dict[str, Any]) -> str:
    """Return the SHA-256 digest used to detect provider replay conflicts."""

    return hashlib.sha256(canonical_provider_payload_bytes(payload)).hexdigest()


@event.listens_for(ProviderInbox, "before_insert")
def _set_provider_payload_digest(
    mapper: Mapper[Any],
    connection: object,
    target: ProviderInbox,
) -> None:
    del mapper, connection
    if not target.payload_digest:
        target.payload_digest = provider_payload_digest(target.payload)


__all__ = [
    "ProviderInbox",
    "ProviderInboxStatus",
    "canonical_provider_payload_bytes",
    "provider_payload_digest",
    "utc_now",
]
