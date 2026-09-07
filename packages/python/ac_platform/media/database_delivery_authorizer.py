"""Request-bound SQL authorization for approved activity media delivery.

Signed URLs are delivery credentials, never enrollment or progress authority.
The existing media grant owns revocation/expiry; its fingerprint pins the
browser and learning scope without changing canonical watch-evidence sessions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.learning.services import (
    ActivityDefinition,
    ActivityService,
    ActivityState,
    LearningAccessContext,
    SqlAlchemyLearningRepository,
)
from ac_platform.media.bindings import (
    ActivityMediaBindingSnapshot,
    resolve_activity_media_binding,
    resolve_activity_media_binding_for_learning,
)
from ac_platform.media.delivery import MediaTokenType
from ac_platform.media.errors import MediaForbidden
from ac_platform.media.models import ActivityMediaBinding, MediaPlaybackGrant
from ac_platform.media.policy import PersistedMediaGrantScope
from ac_platform.media.signing import MediaSigner

DeliveryActivityResolver = Callable[[object, object], ActivityDefinition]
_SCOPE_FIELDS = (
    "tenant_id",
    "person_id",
    "session_id",
    "activity_id",
    "activity_version",
    "asset_id",
    "version_id",
    "enrollment_id",
    "binding_id",
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def activity_delivery_scope(
    actor: ActorContext, binding: ActivityMediaBindingSnapshot, enrollment_id: UUID
) -> dict[str, str]:
    return {
        "tenant_id": str(binding.tenant_id),
        "person_id": str(actor.person_id),
        "session_id": str(actor.session_id),
        "activity_id": str(binding.activity_id),
        "activity_version": binding.activity_version,
        "asset_id": str(binding.asset_id),
        "version_id": str(binding.version_id),
        "enrollment_id": str(enrollment_id),
        "binding_id": str(binding.binding_id),
    }


def activity_delivery_fingerprint(claims: Mapping[str, object]) -> str:
    values = {name: claims.get(name) for name in _SCOPE_FIELDS}
    if any(
        not isinstance(value, str) or not value or len(value) > 128 for value in values.values()
    ):
        raise MediaForbidden("The activity delivery scope is invalid.")
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def grant_token(grant: MediaPlaybackGrant, signer: MediaSigner) -> str:
    """Reproduce the existing persisted grant token solely to verify its digest."""
    return signer.sign(
        {
            "tenant_id": str(grant.tenant_id),
            "actor_id": str(grant.actor_person_id),
            "media_id": str(grant.asset_id),
            "version_id": str(grant.version_id),
            "session_id": str(grant.session_id),
        },
        now=_utc(grant.created_at),
        lifetime=_utc(grant.expires_at) - _utc(grant.created_at),
        token_type="playback",  # noqa: S106 - token kind, not a credential
        nonce=grant.token_nonce,
    )


def require_activity_delivery_access(
    database: Session,
    actor: ActorContext,
    binding: ActivityMediaBindingSnapshot,
    enrollment_id: UUID,
    *,
    activity_resolver: DeliveryActivityResolver,
    now: datetime,
) -> LearningAccessContext:
    """Re-use canonical learning access and prerequisites, not media-owned rules."""
    if actor.tenant_id != binding.tenant_id:
        raise MediaForbidden("The activity delivery scope is unavailable.")
    identity = database.scalar(
        select(IdentitySession)
        .join(Person, Person.id == IdentitySession.person_id)
        .where(
            IdentitySession.id == actor.session_id,
            IdentitySession.person_id == actor.person_id,
            IdentitySession.selected_tenant_id == actor.tenant_id,
            IdentitySession.revoked_at.is_(None),
            IdentitySession.expires_at > now,
            Person.status == "active",
        )
    )
    if identity is None:
        raise MediaForbidden("The activity delivery session is unavailable.")
    store = SqlAlchemyLearningRepository(
        database,
        activity_resolver=activity_resolver,
        reviewer_resolver=lambda _access: None,
        activity_media_resolver=resolve_activity_media_binding_for_learning,
    )
    # Calling the service revalidates membership, entitlement, pinned catalog
    # scope and authoritative prerequisite evidence, including version changes.
    state = ActivityService(store, clock=lambda: now).current_state(
        actor=actor,
        tenant_id=binding.tenant_id,
        enrollment_id=enrollment_id,
        program_version_id=binding.program_version_id,
        activity_id=binding.activity_id,
    )
    if state is ActivityState.LOCKED:
        raise MediaForbidden("The activity delivery prerequisites are unavailable.")
    access = store.resolve_access(
        actor=actor,
        tenant_id=binding.tenant_id,
        enrollment_id=enrollment_id,
        program_version_id=binding.program_version_id,
        activity_id=binding.activity_id,
    )
    if (
        access.activity.module_id != binding.module_id
        or access.activity.version != binding.activity_version
        or access.program.id != binding.program_id
        or access.program.program_scope != binding.program_scope
        or access.program.program_owner_key != binding.program_owner_key
    ):
        raise MediaForbidden("The activity delivery catalog scope is unavailable.")
    return access


class DatabaseMediaDeliveryAuthorizer:
    """One authenticated request and transaction; never reuse across requests."""

    def __init__(
        self,
        database: Session,
        actor: ActorContext,
        *,
        signer: MediaSigner,
        activity_resolver: DeliveryActivityResolver,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database
        self.actor = actor
        self.signer = signer
        self.activity_resolver = activity_resolver
        self.clock = clock

    def authorize(self, claims: Mapping[str, object], token_type: MediaTokenType) -> bool:
        try:
            return self._authorize(claims, token_type)
        except (DomainError, ValueError, TypeError, KeyError):
            return False

    def _authorize(self, claims: Mapping[str, object], token_type: MediaTokenType) -> bool:
        if token_type != "playback":  # noqa: S105 - token kind, not a credential
            return False
        scope = PersistedMediaGrantScope.from_claims(claims)
        if scope is None or any(
            claims.get(name) != value
            for name, value in (
                ("tenant_id", str(self.actor.tenant_id)),
                ("person_id", str(self.actor.person_id)),
                ("session_id", str(self.actor.session_id)),
            )
        ):
            return False
        now = _utc(self.clock())
        grant = self.database.scalar(
            select(MediaPlaybackGrant)
            .where(
                MediaPlaybackGrant.id == scope.delivery_grant_id,
                MediaPlaybackGrant.tenant_id == self.actor.tenant_id,
                MediaPlaybackGrant.actor_person_id == self.actor.person_id,
                MediaPlaybackGrant.revoked_at.is_(None),
                MediaPlaybackGrant.expires_at > now,
            )
            .execution_options(populate_existing=True)
        )
        if grant is None or (
            claims.get("asset_id") != str(grant.asset_id)
            or claims.get("version_id") != str(grant.version_id)
            or claims.get("iat") != int(_utc(grant.created_at).timestamp())
            or claims.get("exp") != int(_utc(grant.expires_at).timestamp())
            or not hmac.compare_digest(
                grant.request_fingerprint, activity_delivery_fingerprint(claims)
            )
            or not hmac.compare_digest(
                grant.token_digest, self.signer.digest(grant_token(grant, self.signer))
            )
        ):
            return False
        row = self.database.scalar(
            select(ActivityMediaBinding)
            .where(
                ActivityMediaBinding.id == scope.binding_id,
                ActivityMediaBinding.tenant_id == self.actor.tenant_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            return False
        binding = resolve_activity_media_binding(
            self.database,
            tenant_id=row.tenant_id,
            activity_id=row.activity_id,
            module_id=row.module_id,
            program_version_id=row.program_version_id,
            program_id=row.program_id,
            program_scope=row.program_scope,
            program_owner_key=row.program_owner_key,
        )
        if binding is None or any(
            claims.get(name) != value
            for name, value in activity_delivery_scope(
                self.actor, binding, scope.enrollment_id
            ).items()
        ):
            return False
        require_activity_delivery_access(
            self.database,
            self.actor,
            binding,
            scope.enrollment_id,
            activity_resolver=self.activity_resolver,
            now=now,
        )
        return True


__all__ = ["DatabaseMediaDeliveryAuthorizer", "DeliveryActivityResolver"]
