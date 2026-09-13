"""Owner-requested provider configuration behind current AC admin authorization.

Saving a configuration does not dispatch inference, grant processing minutes,
validate a provider's price/privacy terms, or publish a report.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration
from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership

CONTROL_ACCOUNT = "admin@authorityclosers.com"


async def lock_provider_configuration(
    database: AsyncSession,
    tenant_id: UUID,
    *,
    shared: bool = False,
) -> None:
    # Appending a new revision must serialize with a current approved dispatch.
    # Locking only the latest row cannot prevent insertion of its successor.
    function = func.pg_advisory_xact_lock_shared if shared else func.pg_advisory_xact_lock
    await database.execute(select(function(725901, tenant_id.int % (2**31))))


class ConversationProviderAdmin:
    def __init__(self, application: ConversationApplication) -> None:
        self.application = application
        self.database = application.database

    async def admit(self, actor: ActorContext) -> None:
        await self.application.admit(actor)
        person = await self.database.get(Person, actor.person_id)
        membership = await self.database.get(Membership, (actor.tenant_id, actor.person_id))
        if (
            person is None
            or (person.email or "").casefold() != CONTROL_ACCOUNT
            or person.email_verified_at is None
            or membership is None
            or membership.role not in {"owner", "admin"}
            or "admin_surface" not in actor.permissions
        ):
            raise ConversationDenied("Provider settings require the verified AC control account.")

    @staticmethod
    def _view(row: ConversationProviderConfiguration) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "revision": row.revision,
            "configuration_sha256": row.configuration_sha256,
            "configuration": row.configuration,
            "created_at": utc(row.created_at).isoformat(),
            "execution_activated": False,
        }

    async def current(self, actor: ActorContext) -> dict[str, Any] | None:
        await self.admit(actor)
        row = await self.database.scalar(
            select(ConversationProviderConfiguration)
            .where(ConversationProviderConfiguration.tenant_id == actor.tenant_id)
            .order_by(ConversationProviderConfiguration.revision.desc())
            .limit(1)
        )
        return None if row is None else self._view(row)

    async def save(
        self,
        actor: ActorContext,
        configuration: Mapping[str, Any],
        *,
        expected_revision: int,
        key: str,
    ) -> dict[str, Any]:
        await self.admit(actor)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ConversationError("Use the current configuration revision.")
        assert actor.tenant_id is not None
        await lock_provider_configuration(self.database, actor.tenant_id)
        try:
            resolved = parse_registry_config(configuration)
        except (ValueError, TypeError, KeyError):
            raise ConversationError(
                "Use valid provider settings and external secret references."
            ) from None
        if resolved.policy.allow_paid or any(
            (item.max_cost_paise or 0) > 0 for item in resolved.providers
        ):
            raise ConversationDenied("This test workspace permits zero paid spend only.")
        payload = {
            "configuration": resolved.as_dict(),
            "expected_revision": expected_revision,
        }
        replay = await self.application._replay(actor, key, "provider_configuration", payload)
        if replay is not None and replay.result_id is not None:
            row = await self.database.get(ConversationProviderConfiguration, replay.result_id)
            if row is None or row.tenant_id != actor.tenant_id:
                raise ConversationConflict("The saved configuration receipt is unavailable.")
            return self._view(row)
        latest = await self.current(actor)
        if (0 if latest is None else latest["revision"]) != expected_revision:
            raise ConversationConflict("Provider settings changed. Reload before saving.")
        now = utc(self.application.clock())
        row = ConversationProviderConfiguration(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            session_id=actor.session_id,
            revision=expected_revision + 1,
            configuration_sha256=resolved.digest,
            configuration=resolved.as_dict(),
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "provider_configuration",
            payload,
            row.id,
            now,
            resource_type="conversation_provider_configuration",
        )
        return self._view(row)
