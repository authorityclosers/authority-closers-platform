"""Append-only retention and deletion hooks for media object history.

The media service owns canonical version state; object deletion is an
operator/worker concern.  Hooks therefore receive immutable references and may
schedule a deletion, but the default hook never deletes anything.  A concrete
deletion worker must be explicitly composed with a reviewed retention policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from ac_platform.media.storage import PrivateObjectStorage


class MediaLifecycleAction(StrEnum):
    OBJECT_MATERIALIZED = "object_materialized"
    VERSION_SUPERSEDED = "version_superseded"
    ASSET_RETIRED = "asset_retired"
    OUTPUT_CLEANUP_RETRYABLE = "output_cleanup_retryable"
    DELETE_SCHEDULED = "delete_scheduled"
    DELETE_COMPLETED = "delete_completed"


@dataclass(frozen=True, slots=True)
class MediaObjectReference:
    """Tenant-scoped, immutable object reference supplied to lifecycle hooks."""

    tenant_id: UUID
    asset_id: UUID
    version_id: UUID
    object_key: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.tenant_id, self.asset_id, self.version_id)
        ):
            raise TypeError("media object identity must use UUID values")
        key = self.object_key.strip()
        if (
            not key
            or key != self.object_key
            or len(key) > 512
            or ".." in key
            or "\\" in key
            or key.startswith("/")
            or any(character.isspace() for character in key)
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in key)
            or not key.startswith(f"tenants/{self.tenant_id}/")
        ):
            raise ValueError("media object key is invalid")
        object.__setattr__(self, "object_key", key)


@dataclass(frozen=True, slots=True)
class MediaRetentionPolicy:
    """Explicit retention decision; no default schedule is inferred."""

    policy_id: str
    superseded_after: timedelta | None = None
    retired_after: timedelta | None = None
    delete_objects: bool = False

    def __post_init__(self) -> None:
        policy_id = self.policy_id.strip()
        if (
            not policy_id
            or len(policy_id) > 128
            or any(character.isspace() for character in policy_id)
        ):
            raise ValueError("media retention policy id must be bounded and nonblank")
        for value in (self.superseded_after, self.retired_after):
            if value is not None and value <= timedelta(0):
                raise ValueError("media retention windows must be positive")
        if not isinstance(self.delete_objects, bool):
            raise TypeError("media retention delete_objects must be a boolean")
        object.__setattr__(self, "policy_id", policy_id)


@dataclass(frozen=True, slots=True)
class MediaLifecycleEvent:
    action: MediaLifecycleAction | str
    reference: MediaObjectReference
    occurred_at: datetime
    not_before: datetime | None = None
    policy_id: str | None = None
    reason_code: str | None = None
    object_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            action = MediaLifecycleAction(self.action)
        except ValueError as error:
            raise ValueError("media lifecycle action is unsupported") from error
        if not isinstance(self.reference, MediaObjectReference):
            raise TypeError("media lifecycle event reference is invalid")
        occurred_at = self.occurred_at
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("media lifecycle event time must be timezone-aware")
        occurred_at = occurred_at.astimezone(UTC)
        not_before = self.not_before
        if not_before is not None:
            if not_before.tzinfo is None or not_before.utcoffset() is None:
                raise ValueError("media lifecycle schedule time must be timezone-aware")
            not_before = not_before.astimezone(UTC)
            if not_before < occurred_at:
                raise ValueError("media lifecycle schedule cannot precede the event")
        if self.policy_id is not None:
            policy_id = self.policy_id.strip()
            if not policy_id or len(policy_id) > 128:
                raise ValueError("media lifecycle policy id is invalid")
            object.__setattr__(self, "policy_id", policy_id)
        if self.reason_code is not None:
            reason_code = self.reason_code.strip()
            if (
                not reason_code
                or len(reason_code) > 128
                or any(character.isspace() for character in reason_code)
            ):
                raise ValueError("media lifecycle reason code is invalid")
            object.__setattr__(self, "reason_code", reason_code)
        object_keys = tuple(self.object_keys)
        if any(
            not isinstance(object_key, str)
            or not object_key.startswith(self.reference.object_key + "/")
            or any(character.isspace() for character in object_key)
            or ".." in object_key
            or "\\" in object_key
            for object_key in object_keys
        ):
            raise ValueError("media lifecycle cleanup inventory is invalid")
        if len(set(object_keys)) != len(object_keys):
            raise ValueError("media lifecycle cleanup inventory must be unique")
        object.__setattr__(self, "object_keys", object_keys)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "not_before", not_before)


class MediaLifecycleHooks(Protocol):
    """Outbox/worker hook for object inventory and lifecycle transitions."""

    def objects_materialized(
        self,
        reference: MediaObjectReference,
        object_keys: Sequence[str],
    ) -> None: ...

    def object_references(
        self,
        reference: MediaObjectReference,
    ) -> tuple[MediaObjectReference, ...]: ...

    def version_superseded(
        self,
        reference: MediaObjectReference,
        *,
        superseded_at: datetime,
        policy: MediaRetentionPolicy | None = None,
    ) -> None: ...

    def asset_retired(
        self,
        reference: MediaObjectReference,
        *,
        retired_at: datetime,
        policy: MediaRetentionPolicy | None = None,
    ) -> None: ...

    def outputs_cleanup_failed(
        self,
        reference: MediaObjectReference,
        *,
        object_keys: Sequence[str],
        reason_code: str,
    ) -> None: ...


class NoopMediaLifecycleHooks:
    """Default hook that records no external effect and deletes nothing."""

    def objects_materialized(
        self,
        reference: MediaObjectReference,
        object_keys: Sequence[str],
    ) -> None:
        del reference, object_keys

    def object_references(
        self,
        reference: MediaObjectReference,
    ) -> tuple[MediaObjectReference, ...]:
        return (reference,)

    def version_superseded(
        self,
        reference: MediaObjectReference,
        *,
        superseded_at: datetime,
        policy: MediaRetentionPolicy | None = None,
    ) -> None:
        del reference, superseded_at, policy

    def asset_retired(
        self,
        reference: MediaObjectReference,
        *,
        retired_at: datetime,
        policy: MediaRetentionPolicy | None = None,
    ) -> None:
        del reference, retired_at, policy

    def outputs_cleanup_failed(
        self,
        reference: MediaObjectReference,
        *,
        object_keys: Sequence[str],
        reason_code: str,
    ) -> None:
        # The no-op hook is intentionally not a cleanup acknowledgement.  The
        # service treats failures against this hook as unavailable rather than
        # claiming that a retryable lifecycle event was durably recorded.
        del reference, object_keys, reason_code


class InMemoryMediaLifecycleHooks:
    """Safe local/test hook; it only stores immutable lifecycle events."""

    def __init__(self) -> None:
        self.events: list[MediaLifecycleEvent] = []
        self._materialized: dict[tuple[UUID, UUID, UUID], tuple[MediaObjectReference, ...]] = {}

    @staticmethod
    def _identity(reference: MediaObjectReference) -> tuple[UUID, UUID, UUID]:
        return reference.tenant_id, reference.asset_id, reference.version_id

    def objects_materialized(
        self,
        reference: MediaObjectReference,
        object_keys: Sequence[str],
    ) -> None:
        """Record every generated playlist/segment under its owning version."""

        identity = self._identity(reference)
        current = list(self._materialized.get(identity, (reference,)))
        known = {item.object_key for item in current}
        for object_key in object_keys:
            if not isinstance(object_key, str):
                raise ValueError("media object inventory keys must be strings")
            key = object_key.strip()
            if (
                not key
                or ".." in key
                or "\\" in key
                or key.startswith("/")
                or any(character.isspace() for character in key)
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in key)
                or not key.startswith(reference.object_key + "/")
            ):
                raise ValueError("media object inventory escaped its version namespace")
            if key in known:
                continue
            materialized = MediaObjectReference(
                tenant_id=reference.tenant_id,
                asset_id=reference.asset_id,
                version_id=reference.version_id,
                object_key=key,
            )
            current.append(materialized)
            known.add(key)
            self.events.append(
                MediaLifecycleEvent(
                    action=MediaLifecycleAction.OBJECT_MATERIALIZED,
                    reference=materialized,
                    occurred_at=datetime.now(UTC),
                )
            )
        self._materialized[identity] = tuple(current)

    def object_references(
        self,
        reference: MediaObjectReference,
    ) -> tuple[MediaObjectReference, ...]:
        return self._materialized.get(self._identity(reference), (reference,))

    def _inventory(self, reference: MediaObjectReference) -> tuple[MediaObjectReference, ...]:
        return self.object_references(reference)

    def _has_event(
        self,
        action: MediaLifecycleAction,
        reference: MediaObjectReference,
    ) -> bool:
        return any(event.action is action and event.reference == reference for event in self.events)

    def version_superseded(
        self,
        reference: MediaObjectReference,
        *,
        superseded_at: datetime,
        policy: MediaRetentionPolicy | None = None,
    ) -> None:
        not_before = (
            superseded_at + policy.superseded_after
            if policy is not None and policy.superseded_after is not None
            else None
        )
        for item in self._inventory(reference):
            if not self._has_event(MediaLifecycleAction.VERSION_SUPERSEDED, item):
                self.events.append(
                    MediaLifecycleEvent(
                        action=MediaLifecycleAction.VERSION_SUPERSEDED,
                        reference=item,
                        occurred_at=superseded_at,
                        not_before=not_before,
                        policy_id=policy.policy_id if policy is not None else None,
                    )
                )
            if (
                not_before is not None
                and policy is not None
                and policy.delete_objects
                and not self._has_event(MediaLifecycleAction.DELETE_SCHEDULED, item)
            ):
                self.events.append(
                    MediaLifecycleEvent(
                        action=MediaLifecycleAction.DELETE_SCHEDULED,
                        reference=item,
                        occurred_at=superseded_at,
                        not_before=not_before,
                        policy_id=policy.policy_id,
                    )
                )

    def asset_retired(
        self,
        reference: MediaObjectReference,
        *,
        retired_at: datetime,
        policy: MediaRetentionPolicy | None = None,
    ) -> None:
        not_before = (
            retired_at + policy.retired_after
            if policy is not None and policy.retired_after is not None
            else None
        )
        for item in self._inventory(reference):
            if not self._has_event(MediaLifecycleAction.ASSET_RETIRED, item):
                self.events.append(
                    MediaLifecycleEvent(
                        action=MediaLifecycleAction.ASSET_RETIRED,
                        reference=item,
                        occurred_at=retired_at,
                        not_before=not_before,
                        policy_id=policy.policy_id if policy is not None else None,
                    )
                )
            if (
                not_before is not None
                and policy is not None
                and policy.delete_objects
                and not self._has_event(MediaLifecycleAction.DELETE_SCHEDULED, item)
            ):
                self.events.append(
                    MediaLifecycleEvent(
                        action=MediaLifecycleAction.DELETE_SCHEDULED,
                        reference=item,
                        occurred_at=retired_at,
                        not_before=not_before,
                        policy_id=policy.policy_id,
                    )
                )

    def outputs_cleanup_failed(
        self,
        reference: MediaObjectReference,
        *,
        object_keys: Sequence[str],
        reason_code: str,
    ) -> None:
        """Record a retry request; production must back this port with an outbox."""

        normalized_keys = tuple(dict.fromkeys(object_keys))
        for object_key in normalized_keys:
            if not isinstance(object_key, str) or not object_key.startswith(
                reference.object_key + "/"
            ):
                raise ValueError("media cleanup inventory escaped its version namespace")
        self.events.append(
            MediaLifecycleEvent(
                action=MediaLifecycleAction.OUTPUT_CLEANUP_RETRYABLE,
                reference=reference,
                occurred_at=datetime.now(UTC),
                reason_code=reason_code,
                object_keys=normalized_keys,
            )
        )


class MediaObjectDeletionWorker:
    """Explicit deletion worker for due lifecycle events.

    The worker does not delete database rows.  Version and audit history remain
    authoritative; only private object bytes are removed after a caller has
    supplied a due, policy-approved event.
    """

    def __init__(self, storage: PrivateObjectStorage) -> None:
        self.storage = storage

    def delete_due(
        self,
        events: Sequence[MediaLifecycleEvent],
        *,
        now: datetime | None = None,
    ) -> tuple[MediaLifecycleEvent, ...]:
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("deletion worker now must be timezone-aware")
        current = current.astimezone(UTC)
        deleted: list[MediaLifecycleEvent] = []
        completed = {
            (
                event.reference.tenant_id,
                event.reference.asset_id,
                event.reference.version_id,
                event.reference.object_key,
            )
            for event in events
            if event.action is MediaLifecycleAction.DELETE_COMPLETED
        }
        scheduled_seen: set[tuple[UUID, UUID, UUID, str]] = set()
        for event in events:
            if event.action not in {
                MediaLifecycleAction.DELETE_SCHEDULED,
                MediaLifecycleAction.OUTPUT_CLEANUP_RETRYABLE,
            }:
                continue
            not_before: datetime | None
            if event.action is MediaLifecycleAction.OUTPUT_CLEANUP_RETRYABLE:
                object_keys = event.object_keys
                if not object_keys:
                    try:
                        object_keys = tuple(
                            key
                            for key in self.storage.list_prefix(event.reference.object_key)
                            if key != event.reference.object_key
                        )
                    except Exception as error:
                        raise RuntimeError("media output cleanup inventory failed") from error
                not_before = event.not_before or current
            else:
                object_keys = (event.reference.object_key,)
                not_before = event.not_before
            for object_key in object_keys:
                identity = (
                    event.reference.tenant_id,
                    event.reference.asset_id,
                    event.reference.version_id,
                    object_key,
                )
                if identity in completed or identity in scheduled_seen:
                    continue
                scheduled_seen.add(identity)
                if not_before is None or current < not_before:
                    continue
                try:
                    self.storage.delete(object_key)
                except Exception as error:
                    # Do not expose adapter/provider details; the caller can
                    # retry the same immutable event through its durable queue.
                    raise RuntimeError("media object deletion failed") from error
                child_reference = event.reference
                if object_key != event.reference.object_key:
                    child_reference = MediaObjectReference(
                        tenant_id=event.reference.tenant_id,
                        asset_id=event.reference.asset_id,
                        version_id=event.reference.version_id,
                        object_key=object_key,
                    )
                deleted.append(
                    MediaLifecycleEvent(
                        action=MediaLifecycleAction.DELETE_COMPLETED,
                        reference=child_reference,
                        occurred_at=current,
                        policy_id=event.policy_id,
                        reason_code=event.reason_code,
                    )
                )
        return tuple(deleted)


# Friendly aliases for composition code that speaks in terms of retention
# rather than lifecycle hooks.
MediaRetentionHooks = MediaLifecycleHooks
NoopMediaRetentionHooks = NoopMediaLifecycleHooks


__all__ = [
    "InMemoryMediaLifecycleHooks",
    "MediaLifecycleAction",
    "MediaLifecycleEvent",
    "MediaLifecycleHooks",
    "MediaObjectDeletionWorker",
    "MediaObjectReference",
    "MediaRetentionHooks",
    "MediaRetentionPolicy",
    "NoopMediaLifecycleHooks",
    "NoopMediaRetentionHooks",
]
