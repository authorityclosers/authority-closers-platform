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

from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.models import (
    ConversationProviderActivation,
    ConversationProviderConfiguration,
)
from ac_platform.conversation_intelligence.provider_registry import (
    DispatchRequest,
    ProviderRegistryError,
    parse_registry_config,
    resolve_dispatch,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership

CONTROL_ACCOUNT = "admin@authorityclosers.com"
# Explicitly named by the AC owner for staging and production administration.
# An email match never substitutes for verified identity or scoped admin access.
CONTROL_ACCOUNTS = frozenset(
    {CONTROL_ACCOUNT, "dipak@authorityclosers.com", "suyash@authorityclosers.com"}
)


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
            or (person.email or "").casefold() not in CONTROL_ACCOUNTS
            or person.email_verified_at is None
            or membership is None
            or membership.role not in {"owner", "admin"}
            or "admin_surface" not in actor.permissions
        ):
            raise ConversationDenied("Provider settings require the verified AC control account.")

    @staticmethod
    def _activation_view(row: ConversationProviderActivation | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": str(row.id),
            "sequence": row.sequence,
            "revision": row.configuration_revision,
            "configuration_sha256": row.configuration_sha256,
            "created_at": utc(row.created_at).isoformat(),
        }

    @staticmethod
    def _view(
        row: ConversationProviderConfiguration,
        activation: ConversationProviderActivation | None = None,
    ) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "revision": row.revision,
            "configuration_sha256": row.configuration_sha256,
            "configuration": row.configuration,
            "created_at": utc(row.created_at).isoformat(),
            # This describes the next-plan selection only. It is deliberately
            # separate from worker/provider runtime health.
            "execution_activated": activation is not None,
            "activation": ConversationProviderAdmin._activation_view(activation),
        }

    async def _active(self, tenant_id: UUID) -> ConversationProviderActivation | None:
        value = await self.database.scalar(
            select(ConversationProviderActivation)
            .where(ConversationProviderActivation.tenant_id == tenant_id)
            .order_by(ConversationProviderActivation.sequence.desc())
            .limit(1)
        )
        return value

    @staticmethod
    def _route_stage(task: str) -> str | None:
        return {"asr": "C2", "facts": "C4", "coaching": "C5"}.get(task)

    @staticmethod
    def _approved_route(
        bundle: HostedApprovalBundle,
        *,
        configuration_sha256: str,
        stage: str,
        provider_id: str,
        model_id: str,
        recipe_revision: str,
    ) -> tuple[Any, ...]:
        policy = bundle.acquisition_policy
        if policy is None:
            # Exact-source StageApproval rows cannot authorize a global Admin
            # selection for the next recording. Future sources need the
            # release-bound acquisition template instead.
            return ()
        return tuple(
            item
            for stages in policy.stage_sets()
            for item in stages
            if (
                item.configuration_sha256,
                item.stage,
                item.provider_id,
                item.model_id,
                item.recipe_revision,
            )
            == (configuration_sha256, stage, provider_id, model_id, recipe_revision)
        )

    @classmethod
    def _approved_configuration(
        cls, configuration: ConversationProviderConfiguration, bundle: HostedApprovalBundle
    ) -> tuple[Any, ...]:
        try:
            config = parse_registry_config(configuration.configuration)
            if config.digest != configuration.configuration_sha256:
                raise ValueError
            if configuration.tenant_id != bundle.provider_control_tenant_id:
                raise ValueError
            if bundle.acquisition_policy is None:
                raise ValueError
            required = {"asr", "facts", "coaching"}
            if {route.task for route in config.routes} < required:
                raise ValueError
            dispatches: list[Any] = []
            stage_costs: dict[str, int] = {}
            stage_max_requests: dict[str, int] = {}
            for route in config.routes:
                stage = cls._route_stage(route.task)
                if stage is None:
                    continue
                provider = next(
                    item
                    for item in config.providers
                    if (item.provider_id, item.model_id) == (route.provider_id, route.model_id)
                )
                dispatch = resolve_dispatch(
                    config,
                    DispatchRequest(
                        route.task,
                        config.revision,
                        config.digest,
                        provider.permission_ref or "",
                        route.required_input_stage,
                    ),
                )
                candidates = cls._approved_route(
                    bundle,
                    configuration_sha256=config.digest,
                    stage=stage,
                    provider_id=dispatch.provider_id,
                    model_id=dispatch.model_id,
                    recipe_revision=dispatch.recipe_revision,
                )
                if not candidates:
                    raise ValueError
                for candidate in candidates:
                    if (
                        candidate.max_cost_paise != dispatch.max_cost_paise
                        or candidate.credential_ref != provider.credential_ref
                        or candidate.provider_terms_ref != provider.provider_terms_ref
                        or candidate.privacy_ref != provider.privacy_ref
                        or candidate.pricing_ref != provider.pricing_ref
                        or candidate.free_allowance_ref != provider.free_allowance_ref
                        or candidate.permission_ref != provider.permission_ref
                    ):
                        continue
                    dispatches.append(dispatch)
                    stage_costs[stage] = dispatch.max_cost_paise
                    stage_max_requests[stage] = candidate.max_requests
                    break
                else:
                    raise ValueError
            # C2 transcription and C5 coaching run once. C4 is the only
            # stage whose approved request count fans out for chunk/retry
            # work. The cap therefore covers one C2, all approved C4
            # requests, and one C5; multiplying every stage by max_requests
            # would reject valid configurations and misstate the budget.
            projected_cost_paise = (
                stage_costs["C2"] + stage_costs["C4"] * stage_max_requests["C4"] + stage_costs["C5"]
            )
            if projected_cost_paise > bundle.budget_cap_paise:
                raise ValueError
            if any(item.max_cost_paise > 0 for item in dispatches) and (
                not config.policy.allow_paid
                or config.policy.paid_approval_ref != bundle.paid_approval_ref
            ):
                raise ValueError
            return tuple(dispatches)
        except (ProviderRegistryError, StopIteration, TypeError, ValueError):
            raise ConversationDenied(
                "This provider revision is not in the pinned activation approval."
            ) from None

    async def _activation_options(
        self, actor: ActorContext, bundle: HostedApprovalBundle | None
    ) -> list[dict[str, Any]]:
        if bundle is None or actor.tenant_id != bundle.provider_control_tenant_id:
            return []
        rows = (
            await self.database.scalars(
                select(ConversationProviderConfiguration)
                .where(ConversationProviderConfiguration.tenant_id == actor.tenant_id)
                .order_by(ConversationProviderConfiguration.revision.desc())
                .limit(64)
            )
        ).all()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                dispatches = self._approved_configuration(row, bundle)
            except ConversationDenied:
                continue
            result.append(
                {
                    "id": str(row.id),
                    "revision": row.revision,
                    "configuration_sha256": row.configuration_sha256,
                    "routes": [
                        {
                            "task": item.task,
                            "provider": item.provider_id,
                            "model": item.model_id,
                            "max_cost_paise": item.max_cost_paise,
                        }
                        for item in dispatches
                    ],
                }
            )
        return result

    async def current(
        self, actor: ActorContext, *, bundle: HostedApprovalBundle | None = None
    ) -> dict[str, Any] | None:
        await self.admit(actor)
        row = await self.database.scalar(
            select(ConversationProviderConfiguration)
            .where(ConversationProviderConfiguration.tenant_id == actor.tenant_id)
            .order_by(ConversationProviderConfiguration.revision.desc())
            .limit(1)
        )
        if row is None:
            return None
        assert actor.tenant_id is not None
        activation = await self._active(actor.tenant_id)
        value = self._view(row, activation)
        value["activation_options"] = await self._activation_options(actor, bundle)
        return value

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
        paid_providers = tuple(
            item for item in resolved.providers if (item.max_cost_paise or 0) > 0
        )
        if resolved.policy.allow_paid and not paid_providers:
            raise ConversationDenied("Paid policy requires an explicitly priced provider.")
        if paid_providers and not resolved.policy.allow_paid:
            raise ConversationDenied("Paid provider settings require an explicit paid policy.")
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

    async def activate(
        self,
        actor: ActorContext,
        *,
        target_revision: int,
        expected_revision: int,
        key: str,
        bundle: HostedApprovalBundle,
    ) -> dict[str, Any]:
        await self.admit(actor)
        if actor.tenant_id != bundle.provider_control_tenant_id:
            raise ConversationDenied("Provider activation requires the operations workspace.")
        if type(target_revision) is not int or target_revision < 1:
            raise ConversationError("Choose a saved provider revision.")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ConversationError("Use the current configuration revision.")
        await lock_provider_configuration(self.database, actor.tenant_id)
        target = await self.database.scalar(
            select(ConversationProviderConfiguration)
            .where(
                ConversationProviderConfiguration.tenant_id == actor.tenant_id,
                ConversationProviderConfiguration.revision == target_revision,
            )
            .with_for_update(read=True)
        )
        latest = await self.database.scalar(
            select(ConversationProviderConfiguration)
            .where(ConversationProviderConfiguration.tenant_id == actor.tenant_id)
            .order_by(ConversationProviderConfiguration.revision.desc())
            .limit(1)
            .with_for_update(read=True)
        )
        if target is None or latest is None:
            raise ConversationConflict("Provider revision is unavailable. Reload settings.")
        if latest.revision != expected_revision:
            raise ConversationConflict("Provider settings changed. Reload before activating.")
        self._approved_configuration(target, bundle)
        payload = {
            "target_revision": target.revision,
            "configuration_sha256": target.configuration_sha256,
            "approval_bundle_sha256": bundle.digest,
        }
        replay = await self.application._replay(actor, key, "provider_activation", payload)
        if replay is not None and replay.result_id is not None:
            row = await self.database.get(ConversationProviderActivation, replay.result_id)
            if row is None or row.tenant_id != actor.tenant_id:
                raise ConversationConflict("The activation receipt is unavailable.")
            return (await self.current(actor, bundle=bundle)) or {}
        sequence = (
            await self.database.scalar(
                select(func.max(ConversationProviderActivation.sequence)).where(
                    ConversationProviderActivation.tenant_id == actor.tenant_id
                )
            )
            or 0
        ) + 1
        now = utc(self.application.clock())
        row = ConversationProviderActivation(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            session_id=actor.session_id,
            configuration_id=target.id,
            configuration_revision=target.revision,
            configuration_sha256=target.configuration_sha256,
            sequence=sequence,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "provider_activation",
            payload,
            row.id,
            now,
            resource_type="conversation_provider_activation",
        )
        return (await self.current(actor, bundle=bundle)) or {}
