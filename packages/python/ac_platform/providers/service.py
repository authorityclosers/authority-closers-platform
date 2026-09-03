"""Verified webhook and durable provider-inbox services."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.providers.models import (
    ProviderInbox,
    ProviderInboxStatus,
    provider_payload_digest,
    utc_now,
)
from ac_platform.telemetry.redaction import sanitize_error

MAX_PROVIDER_LEASE = timedelta(minutes=15)
MAX_WEBHOOK_BODY_BYTES = 1_000_000


class ProviderWebhookRejected(ValueError):
    """A callback failed provider authenticity, freshness, or parsing checks."""


class DuplicateProviderEvent(ValueError):
    """Optional signal for callers that want to distinguish a replay."""


class ProviderPayloadConflict(DuplicateProviderEvent):
    """The same provider event id was received with different verified facts."""


@dataclass(frozen=True, slots=True)
class WebhookAttribution:
    """Server-owned attribution for one configured provider webhook endpoint."""

    provider: str
    tenant_id: UUID | None = None
    resource_type: str | None = None
    resource_id: str | None = None

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        if not provider:
            raise ValueError("webhook attribution provider must not be blank")
        object.__setattr__(self, "provider", provider)
        if self.resource_type is not None:
            resource_type = self.resource_type.strip()
            if not resource_type:
                raise ValueError("webhook attribution resource_type must not be blank")
            object.__setattr__(self, "resource_type", resource_type)
        if self.resource_id is not None:
            resource_id = self.resource_id.strip()
            if not resource_id:
                raise ValueError("webhook attribution resource_id must not be blank")
            object.__setattr__(self, "resource_id", resource_id)


class TrustedWebhookAdapter:
    """Contract implemented by a server-configured, provider-specific adapter.

    HTTP request data supplies only the raw body, timestamp, and signature.
    Provider, tenant, and resource attribution come from this object and its
    signed-payload resolver; callers cannot override them per request.
    """

    def verify(
        self,
        body: bytes,
        *,
        timestamp: int,
        signature: str,
        now: datetime | None = None,
    ) -> None:
        raise NotImplementedError

    def attribution(self, payload: Mapping[str, Any]) -> WebhookAttribution:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ConfiguredWebhookAdapter(TrustedWebhookAdapter):
    """Concrete adapter built from trusted server configuration."""

    provider: str
    verifier: HmacWebhookVerifier
    tenant_id: UUID | None = None
    resource_type: str | None = None
    resource_id_field: str | None = None

    def __post_init__(self) -> None:
        attribution = WebhookAttribution(
            provider=self.provider,
            tenant_id=self.tenant_id,
            resource_type=self.resource_type,
        )
        object.__setattr__(self, "provider", attribution.provider)
        object.__setattr__(self, "resource_type", attribution.resource_type)
        if self.resource_id_field is not None:
            field = self.resource_id_field.strip()
            if not field:
                raise ValueError("resource_id_field must not be blank")
            object.__setattr__(self, "resource_id_field", field)

    def verify(
        self,
        body: bytes,
        *,
        timestamp: int,
        signature: str,
        now: datetime | None = None,
    ) -> None:
        self.verifier.verify(body, timestamp=timestamp, signature=signature, now=now)

    def attribution(self, payload: Mapping[str, Any]) -> WebhookAttribution:
        resource_id: str | None = None
        if self.resource_id_field is not None:
            raw_resource_id = payload.get(self.resource_id_field)
            if not isinstance(raw_resource_id, str) or not raw_resource_id.strip():
                raise ProviderWebhookRejected(
                    "signed provider webhook resource attribution is missing"
                )
            resource_id = raw_resource_id.strip()
        return WebhookAttribution(
            provider=self.provider,
            tenant_id=self.tenant_id,
            resource_type=self.resource_type,
            resource_id=resource_id,
        )


def _db_time_plus(*, seconds: float, dialect: str | None) -> Any:
    if dialect == "sqlite":
        return func.datetime(func.current_timestamp(), f"+{seconds:g} seconds")
    return func.now() + literal(seconds) * text("INTERVAL '1 second'")


def _lease_seconds(lease_for: timedelta) -> float:
    seconds = lease_for.total_seconds()
    if seconds <= 0 or lease_for > MAX_PROVIDER_LEASE:
        raise ValueError("provider lease must be greater than zero and at most 15 minutes")
    return seconds


def deterministic_provider_retry_delay(event_id: UUID, attempt_count: int) -> timedelta:
    """Return deterministic exponential backoff plus bounded positive jitter."""

    if attempt_count < 1:
        raise ValueError("attempt_count must be at least one")
    base_seconds = min(5 * (2 ** min(attempt_count - 1, 10)), 300)
    remaining = 300 - base_seconds
    if remaining <= 0:
        return timedelta(seconds=300)
    jitter_cap = min(base_seconds * 0.25, remaining)
    sample = int.from_bytes(
        hashlib.sha256(f"{event_id}:{attempt_count}".encode("ascii")).digest()[:2],
        "big",
    )
    jitter = jitter_cap * (sample / 65_535)
    return timedelta(seconds=base_seconds + jitter)


def build_provider_inbox_insert_statement(
    *,
    values: Mapping[str, Any],
    dialect: str = "postgresql",
) -> Any:
    """Build an atomic provider-event dedupe insert."""

    if dialect == "postgresql":
        return (
            postgresql_insert(ProviderInbox)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[ProviderInbox.provider, ProviderInbox.external_event_id]
            )
            .returning(ProviderInbox.id)
        )
    if dialect == "sqlite":
        return (
            sqlite_insert(ProviderInbox)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[ProviderInbox.provider, ProviderInbox.external_event_id]
            )
            .returning(ProviderInbox.id)
        )
    raise ValueError(f"unsupported provider inbox SQL dialect: {dialect}")


def build_provider_inbox_claim_statement(
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> Select[tuple[ProviderInbox]]:
    """Build a row-locking claim query using database time."""

    del now
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    available = and_(
        ProviderInbox.status.in_(
            (ProviderInboxStatus.RECEIVED.value, ProviderInboxStatus.RETRY_WAIT.value)
        ),
        ProviderInbox.available_at <= func.now(),
    )
    expired = and_(
        ProviderInbox.status == ProviderInboxStatus.PROCESSING.value,
        ProviderInbox.processing_lease_until <= func.now(),
    )
    return (
        select(ProviderInbox)
        .where(
            or_(available, expired),
            ProviderInbox.processing_attempts < ProviderInbox.max_processing_attempts,
        )
        .order_by(ProviderInbox.available_at.asc(), ProviderInbox.received_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def build_provider_inbox_take_statement(
    *,
    event_id: UUID,
    lease_token: UUID,
    lease_for: timedelta,
    dialect: str = "postgresql",
) -> Any:
    """Build the fenced transition from available/expired to processing."""

    seconds = _lease_seconds(lease_for)
    available = and_(
        ProviderInbox.status.in_(
            (ProviderInboxStatus.RECEIVED.value, ProviderInboxStatus.RETRY_WAIT.value)
        ),
        ProviderInbox.available_at <= func.now(),
    )
    expired = and_(
        ProviderInbox.status == ProviderInboxStatus.PROCESSING.value,
        ProviderInbox.processing_lease_until <= func.now(),
    )
    return (
        update(ProviderInbox)
        .where(
            ProviderInbox.id == event_id,
            or_(available, expired),
            ProviderInbox.processing_attempts < ProviderInbox.max_processing_attempts,
        )
        .values(
            status=ProviderInboxStatus.PROCESSING.value,
            processing_attempts=ProviderInbox.processing_attempts + 1,
            processing_lease_token=lease_token,
            processing_lease_until=_db_time_plus(seconds=seconds, dialect=dialect),
            processed_at=None,
            dead_lettered_at=None,
            last_error=None,
        )
    )


def build_provider_inbox_acknowledge_statement(
    *,
    event_id: UUID,
    lease_token: UUID,
) -> Any:
    """Build a fenced provider-event acknowledgement statement."""

    return (
        update(ProviderInbox)
        .where(
            ProviderInbox.id == event_id,
            ProviderInbox.status == ProviderInboxStatus.PROCESSING.value,
            ProviderInbox.processing_lease_token == lease_token,
            ProviderInbox.processing_lease_until > func.now(),
        )
        .values(
            status=ProviderInboxStatus.PROCESSED.value,
            processed_at=func.now(),
            processing_lease_token=None,
            processing_lease_until=None,
            dead_lettered_at=None,
            last_error=None,
        )
    )


def build_provider_inbox_renew_statement(
    *,
    event_id: UUID,
    lease_token: UUID,
    lease_for: timedelta,
    dialect: str = "postgresql",
) -> Any:
    """Build a fenced processing-lease renewal using database time."""

    seconds = _lease_seconds(lease_for)
    return (
        update(ProviderInbox)
        .where(
            ProviderInbox.id == event_id,
            ProviderInbox.status == ProviderInboxStatus.PROCESSING.value,
            ProviderInbox.processing_lease_token == lease_token,
            ProviderInbox.processing_lease_until > func.now(),
        )
        .values(processing_lease_until=_db_time_plus(seconds=seconds, dialect=dialect))
    )


def build_provider_inbox_failure_statement(
    *,
    event_id: UUID,
    lease_token: UUID,
    error: str,
    dead_letter: bool,
    retry_delay: timedelta = timedelta(0),
    dialect: str = "postgresql",
) -> Any:
    """Build a live-lease-only retry/dead-letter transition."""

    if retry_delay < timedelta(0) or retry_delay > timedelta(minutes=5):
        raise ValueError("provider retry_delay must be between zero and five minutes")
    values: dict[str, Any] = {
        "status": (
            ProviderInboxStatus.DEAD_LETTER.value
            if dead_letter
            else ProviderInboxStatus.RETRY_WAIT.value
        ),
        "last_error": error,
        "processing_lease_token": None,
        "processing_lease_until": None,
        "processed_at": None,
    }
    if dead_letter:
        values.update(dead_lettered_at=func.now(), available_at=func.now())
    else:
        values.update(
            dead_lettered_at=None,
            available_at=_db_time_plus(
                seconds=retry_delay.total_seconds(),
                dialect=dialect,
            ),
        )
    return (
        update(ProviderInbox)
        .where(
            ProviderInbox.id == event_id,
            ProviderInbox.status == ProviderInboxStatus.PROCESSING.value,
            ProviderInbox.processing_lease_token == lease_token,
            ProviderInbox.processing_lease_until > func.now(),
        )
        .values(**values)
    )


def build_provider_inbox_exhausted_statement() -> Any:
    """Dead-letter expired processing rows that exhausted their attempt budget."""

    return (
        update(ProviderInbox)
        .where(
            ProviderInbox.status == ProviderInboxStatus.PROCESSING.value,
            ProviderInbox.processing_lease_until <= func.now(),
            ProviderInbox.processing_attempts >= ProviderInbox.max_processing_attempts,
        )
        .values(
            status=ProviderInboxStatus.DEAD_LETTER.value,
            processing_lease_token=None,
            processing_lease_until=None,
            dead_lettered_at=func.now(),
            available_at=func.now(),
            last_error="provider inbox processing lease expired at the attempt limit",
        )
    )


class HmacWebhookVerifier:
    """Verify timestamped HMAC callbacks without persisting the shared secret."""

    def __init__(self, secret: bytes, *, tolerance: timedelta = timedelta(minutes=5)) -> None:
        if not secret:
            raise ValueError("webhook secret must not be empty")
        if tolerance <= timedelta(0):
            raise ValueError("tolerance must be positive")
        self._secret = bytes(secret)
        self._tolerance = tolerance

    def verify(
        self,
        body: bytes,
        *,
        timestamp: int,
        signature: str,
        now: datetime | None = None,
    ) -> None:
        current_time = now or datetime.now(UTC)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=UTC)
        age = abs(current_time.timestamp() - timestamp)
        if age > self._tolerance.total_seconds():
            raise ProviderWebhookRejected("provider webhook timestamp is outside the tolerance")
        supplied = signature.strip()
        if supplied.startswith("sha256="):
            supplied = supplied[7:]
        if not supplied:
            raise ProviderWebhookRejected("provider webhook signature is missing")
        signed = f"{timestamp}.".encode("ascii") + body
        expected = hmac.new(self._secret, signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ProviderWebhookRejected("provider webhook signature is invalid")


class ProviderInboxRepository:
    """Insert verified provider events once and process them under bounded leases."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_once(
        self,
        *,
        attribution: WebhookAttribution,
        external_event_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        received_at: datetime | None = None,
        verified_body_digest: str | None = None,
        max_processing_attempts: int = 5,
    ) -> tuple[ProviderInbox, bool]:
        """Return ``(row, created)`` and reject conflicting replays."""

        normalized_provider = self._required(attribution.provider, "provider", 64)
        normalized_event_id = self._required(external_event_id, "external_event_id", 255)
        normalized_event_type = self._required(event_type, "event_type", 160)
        normalized_resource_type = self._optional(attribution.resource_type, "resource_type", 100)
        if not 1 <= max_processing_attempts <= 25:
            raise ValueError("max_processing_attempts must be between 1 and 25")
        if verified_body_digest is not None:
            try:
                digest_bytes = bytes.fromhex(verified_body_digest)
            except ValueError as error:
                raise ValueError("verified_body_digest must be a SHA-256 hex digest") from error
            if len(digest_bytes) != 32:
                raise ValueError("verified_body_digest must be a SHA-256 hex digest")
        normalized_payload = dict(payload)
        payload_digest = provider_payload_digest(normalized_payload)
        existing = await self._session.scalar(
            select(ProviderInbox).where(
                ProviderInbox.provider == normalized_provider,
                ProviderInbox.external_event_id == normalized_event_id,
            )
        )
        if existing is not None:
            self._require_same_event(
                existing,
                event_type=normalized_event_type,
                tenant_id=attribution.tenant_id,
                resource_type=normalized_resource_type,
                resource_id=attribution.resource_id,
                payload_digest=payload_digest,
                verified_body_digest=verified_body_digest,
                max_processing_attempts=max_processing_attempts,
            )
            return existing, False

        received = self._as_utc(received_at or utc_now())
        values = {
            "provider": normalized_provider,
            "external_event_id": normalized_event_id,
            "event_type": normalized_event_type,
            "tenant_id": attribution.tenant_id,
            "resource_type": normalized_resource_type,
            "resource_id": attribution.resource_id,
            "payload": normalized_payload,
            "payload_digest": payload_digest,
            "verified_body_digest": verified_body_digest,
            "received_at": received,
            "available_at": received,
            "max_processing_attempts": max_processing_attempts,
        }
        dialect = self._dialect_name()
        if dialect in {"postgresql", "sqlite"}:
            result = cast(
                Any,
                await self._session.execute(
                    build_provider_inbox_insert_statement(values=values, dialect=dialect)
                ),
            )
            inserted_id = result.scalar_one_or_none()
            if inserted_id is None:
                existing = await self._session.scalar(
                    select(ProviderInbox).where(
                        ProviderInbox.provider == normalized_provider,
                        ProviderInbox.external_event_id == normalized_event_id,
                    )
                )
                if existing is None:
                    raise RuntimeError("provider inbox conflict did not reload a canonical row")
                self._require_same_event(
                    existing,
                    event_type=normalized_event_type,
                    tenant_id=attribution.tenant_id,
                    resource_type=normalized_resource_type,
                    resource_id=attribution.resource_id,
                    payload_digest=payload_digest,
                    verified_body_digest=verified_body_digest,
                    max_processing_attempts=max_processing_attempts,
                )
                return existing, False
            canonical = await self._session.get(ProviderInbox, inserted_id)
            if canonical is None:
                raise RuntimeError("provider inbox insert did not reload its canonical row")
            return canonical, True

        row = ProviderInbox(id=uuid4(), **values)
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            existing = await self._session.scalar(
                select(ProviderInbox).where(
                    ProviderInbox.provider == normalized_provider,
                    ProviderInbox.external_event_id == normalized_event_id,
                )
            )
            if existing is None:
                raise
            self._require_same_event(
                existing,
                event_type=normalized_event_type,
                tenant_id=attribution.tenant_id,
                resource_type=normalized_resource_type,
                resource_id=attribution.resource_id,
                payload_digest=payload_digest,
                verified_body_digest=verified_body_digest,
                max_processing_attempts=max_processing_attempts,
            )
            return existing, False
        return row, True

    async def receive(self, **kwargs: Any) -> tuple[ProviderInbox, bool]:
        return await self.record_once(**kwargs)

    async def claim_processing(
        self,
        *,
        now: datetime | None = None,
        lease_for: timedelta = timedelta(minutes=5),
        limit: int = 1,
    ) -> list[ProviderInbox]:
        _lease_seconds(lease_for)
        if limit != 1:
            raise ValueError("provider inbox processors must claim exactly one event")
        current_time = self._as_utc(now or utc_now())
        await self._session.execute(build_provider_inbox_exhausted_statement())
        candidates = list(
            (await self._session.scalars(build_provider_inbox_claim_statement(limit=limit))).all()
        )
        claimed: list[ProviderInbox] = []
        dialect = self._dialect_name() or "postgresql"
        for row in candidates:
            token = uuid4()
            result = await self._session.execute(
                build_provider_inbox_take_statement(
                    event_id=row.id,
                    lease_token=token,
                    lease_for=lease_for,
                    dialect=dialect,
                )
            )
            rowcount = getattr(result, "rowcount", None)
            if isinstance(rowcount, int):
                if rowcount != 1:
                    continue
                await self._session.refresh(row)
            else:
                row.status = ProviderInboxStatus.PROCESSING.value
                row.processing_attempts += 1
                row.processing_lease_token = token
                row.processing_lease_until = current_time + lease_for
                row.processed_at = None
                row.dead_lettered_at = None
                row.last_error = None
                await self._session.flush()
            claimed.append(row)
        return claimed

    async def mark_processed(
        self,
        event: ProviderInbox | UUID,
        *,
        lease_token: UUID | None = None,
        processed_at: datetime | None = None,
        now: datetime | None = None,
    ) -> ProviderInbox:
        del processed_at
        row = await self._get(event)
        if row.status == ProviderInboxStatus.PROCESSED.value:
            return row
        if lease_token is None:
            raise ValueError("provider event must be acknowledged with its processing lease")
        result = await self._session.execute(
            build_provider_inbox_acknowledge_statement(event_id=row.id, lease_token=lease_token)
        )
        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, int):
            if rowcount != 1:
                raise ValueError("provider processing lease is no longer current")
            await self._session.refresh(row)
        else:
            if not self._lease_is_current(row, lease_token, now or utc_now()):
                raise ValueError("provider processing lease is no longer current")
            row.status = ProviderInboxStatus.PROCESSED.value
            row.processed_at = self._as_utc(now or utc_now())
            row.processing_lease_token = None
            row.processing_lease_until = None
            row.dead_lettered_at = None
            row.last_error = None
            await self._session.flush()
        return row

    async def renew_processing(
        self,
        event: ProviderInbox | UUID,
        lease_token: UUID,
        *,
        lease_for: timedelta = timedelta(minutes=5),
        now: datetime | None = None,
    ) -> ProviderInbox:
        _lease_seconds(lease_for)
        row = await self._get(event)
        result = await self._session.execute(
            build_provider_inbox_renew_statement(
                event_id=row.id,
                lease_token=lease_token,
                lease_for=lease_for,
                dialect=self._dialect_name() or "postgresql",
            )
        )
        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, int):
            if rowcount != 1:
                raise ValueError("provider processing lease is no longer current")
            await self._session.refresh(row)
        else:
            current_time = self._as_utc(now or utc_now())
            if not self._lease_is_current(row, lease_token, current_time):
                raise ValueError("provider processing lease is no longer current")
            row.processing_lease_until = current_time + lease_for
            await self._session.flush()
        return row

    async def mark_failed(
        self,
        event: ProviderInbox | UUID,
        error: str | BaseException,
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
        permanent: bool = False,
    ) -> ProviderInbox:
        row = await self._get(event)
        if lease_token is None:
            raise ValueError("provider event failures require the processing lease token")
        dead_letter = permanent or row.processing_attempts >= row.max_processing_attempts
        delay = (
            timedelta(0)
            if dead_letter
            else deterministic_provider_retry_delay(row.id, row.processing_attempts)
        )
        sanitized = sanitize_error(error)
        result = await self._session.execute(
            build_provider_inbox_failure_statement(
                event_id=row.id,
                lease_token=lease_token,
                error=sanitized,
                dead_letter=dead_letter,
                retry_delay=delay,
                dialect=self._dialect_name() or "postgresql",
            )
        )
        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, int):
            if rowcount != 1:
                raise ValueError("provider processing lease is no longer current")
            await self._session.refresh(row)
        else:
            current_time = self._as_utc(now or utc_now())
            if not self._lease_is_current(row, lease_token, current_time):
                raise ValueError("provider processing lease is no longer current")
            row.status = (
                ProviderInboxStatus.DEAD_LETTER.value
                if dead_letter
                else ProviderInboxStatus.RETRY_WAIT.value
            )
            row.last_error = sanitized
            row.processing_lease_token = None
            row.processing_lease_until = None
            row.processed_at = None
            row.dead_lettered_at = current_time if dead_letter else None
            row.available_at = current_time if dead_letter else current_time + delay
            await self._session.flush()
        return row

    async def ingest_verified(
        self,
        *,
        adapter: TrustedWebhookAdapter,
        body: bytes,
        timestamp: int,
        signature: str,
        max_processing_attempts: int = 5,
        now: datetime | None = None,
    ) -> tuple[ProviderInbox, bool]:
        """Verify and parse the exact same body before any durable inbox write."""

        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            raise ProviderWebhookRejected("provider webhook body exceeds the bounded size")
        adapter.verify(body, timestamp=timestamp, signature=signature, now=now)
        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ProviderWebhookRejected(
                "provider webhook body is not a unique-key JSON object"
            ) from error
        if not isinstance(payload, dict):
            raise ProviderWebhookRejected("provider webhook body must be a JSON object")
        external_event_id = _verified_body_text(payload, "id", 255)
        event_type = _verified_body_text(payload, "type", 160)
        attribution = adapter.attribution(cast(dict[str, Any], payload))
        return await self.record_once(
            attribution=attribution,
            external_event_id=external_event_id,
            event_type=event_type,
            payload=cast(dict[str, Any], payload),
            received_at=now,
            verified_body_digest=hashlib.sha256(body).hexdigest(),
            max_processing_attempts=max_processing_attempts,
        )

    async def _get(self, event: ProviderInbox | UUID) -> ProviderInbox:
        row = (
            event
            if isinstance(event, ProviderInbox)
            else await self._session.get(ProviderInbox, event)
        )
        if row is None:
            raise ValueError("provider inbox event does not exist")
        return row

    def _dialect_name(self) -> str | None:
        bind = self._session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", None)
        return dialect if isinstance(dialect, str) else None

    @staticmethod
    def _require_same_event(
        row: ProviderInbox,
        *,
        event_type: str,
        tenant_id: UUID | None,
        resource_type: str | None,
        resource_id: UUID | str | None,
        payload_digest: str,
        verified_body_digest: str | None,
        max_processing_attempts: int,
    ) -> None:
        if (
            row.event_type != event_type
            or row.tenant_id != tenant_id
            or row.resource_type != resource_type
            or row.resource_id != (str(resource_id) if resource_id is not None else None)
            or row.payload_digest != payload_digest
            or row.verified_body_digest != verified_body_digest
            or row.max_processing_attempts != max_processing_attempts
        ):
            raise ProviderPayloadConflict(
                "provider event id was reused with different verified body or canonical facts"
            )

    @staticmethod
    def _lease_is_current(
        row: ProviderInbox,
        lease_token: UUID | None,
        now: datetime | None,
    ) -> bool:
        if lease_token is None or row.processing_lease_token != lease_token:
            return False
        if row.status != ProviderInboxStatus.PROCESSING.value:
            return False
        if row.processing_lease_until is None:
            return False
        current_time = now or utc_now()
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=UTC)
        return row.processing_lease_until > current_time

    @staticmethod
    def _required(value: str, field_name: str, maximum: int) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be blank")
        if len(normalized) > maximum:
            raise ValueError(f"{field_name} must be at most {maximum} characters")
        return normalized

    @classmethod
    def _optional(cls, value: str | None, field_name: str, maximum: int) -> str | None:
        return cls._required(value, field_name, maximum) if value is not None else None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not permitted: {value}")


def _verified_body_text(payload: Mapping[str, Any], key: str, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ProviderWebhookRejected(f"verified provider body requires string field {key}")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ProviderWebhookRejected(f"verified provider body field {key} is invalid")
    return normalized


__all__ = [
    "DuplicateProviderEvent",
    "HmacWebhookVerifier",
    "MAX_PROVIDER_LEASE",
    "MAX_WEBHOOK_BODY_BYTES",
    "ProviderInboxRepository",
    "ProviderPayloadConflict",
    "ProviderWebhookRejected",
    "build_provider_inbox_acknowledge_statement",
    "build_provider_inbox_claim_statement",
    "build_provider_inbox_exhausted_statement",
    "build_provider_inbox_failure_statement",
    "build_provider_inbox_insert_statement",
    "build_provider_inbox_renew_statement",
    "build_provider_inbox_take_statement",
    "deterministic_provider_retry_delay",
]
