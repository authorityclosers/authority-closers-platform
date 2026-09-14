"""Release-composed allowance and exact provider quote authority.

An opaque reference in an admin form cannot activate processing. The deployment
must supply a separately approved, hash-pinned bundle. Its named source grants
must match the current admin registry. Quote issuance never accepts the quote.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select

from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderPolicy,
    HostedApprovalBundle,
    StageApproval,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    ExecutionPermission,
    MinuteAccount,
    MinuteGrant,
    Quote,
    grant_minutes,
    reserve,
)
from ac_platform.conversation_intelligence.execution_control import require_execution_enabled
from ac_platform.conversation_intelligence.inference import (
    ConversationInference,
    ServicePlan,
    binding_for,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationProviderActivation,
    ConversationProviderConfiguration,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.processing_actor import (
    ConversationActor,
    ProcessingActor,
    same_actor,
)
from ac_platform.conversation_intelligence.provider_admin import (
    CONTROL_ACCOUNTS,
    lock_provider_configuration,
)
from ac_platform.conversation_intelligence.provider_registry import (
    DispatchRequest,
    ProviderRegistryError,
    parse_registry_config,
    resolve_dispatch,
)
from ac_platform.conversation_intelligence.providers import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline, StageRequest
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant

ApprovalLoader = Callable[[], HostedApprovalBundle]


class ConversationAuthority:
    def __init__(
        self, loader: ApprovalLoader, *, environment: str, operations_tenant_id: UUID
    ) -> None:
        if not isinstance(operations_tenant_id, UUID):
            raise ValueError("hosted_operations_tenant_required")
        self.loader, self.environment = loader, environment
        self.operations_tenant_id = operations_tenant_id

    def current(self, now: datetime) -> HostedApprovalBundle:
        try:
            # Never trust model_copy or mutable dictionaries supplied by a caller.
            bundle = HostedApprovalBundle.model_validate_json(self.loader().to_json())
            bundle.current(int(now.timestamp()), self.environment)
            if bundle.provider_control_tenant_id != self.operations_tenant_id:
                raise ValueError("hosted_control_tenant_mismatch")
            if self.environment != "test" and (
                any(item.zero_cost_basis == "synthetic" for item in bundle.stages)
                or (
                    bundle.acquisition_policy is not None
                    and any(
                        item.zero_cost_basis == "synthetic"
                        for stages in bundle.acquisition_policy.stage_sets()
                        for item in stages
                    )
                )
            ):
                raise ValueError("synthetic_approval_not_hosted")
            return bundle
        except (ValueError, TypeError, OSError):
            raise ConversationDenied(
                "The approved processing configuration is unavailable."
            ) from None

    def recipient(self, bundle: HostedApprovalBundle, actor: ConversationActor) -> None:
        if isinstance(actor, ProcessingActor):
            policy = bundle.acquisition_policy
            if policy is None or not policy.matches_actor(actor):
                raise ConversationDenied(
                    "This processing lease has no approved acquisition provider policy."
                )
            return
        if not any(
            item.tenant_id == actor.tenant_id and item.person_id == actor.person_id
            for item in bundle.allowances
        ):
            raise ConversationDenied("This account has no approved processing allowance.")

    async def admit(
        self, app: ConversationApplication, actor: ConversationActor
    ) -> HostedApprovalBundle:
        bundle = self.current(await app.admit(actor))
        self.recipient(bundle, actor)
        return bundle

    async def require_execution_enabled(self, app: ConversationApplication) -> None:
        await require_execution_enabled(
            app.database,
            environment=self.environment,
            operations_tenant_id=self.operations_tenant_id,
        )

    async def claim_allowance(self, app: ConversationApplication, actor: ConversationActor) -> None:
        """POST-only application command; finite grants are never inferred from login."""
        bundle = await self.admit(app, actor)
        db = app.database
        # Serialize first creation of the shared project budget, too. This is a
        # transaction-scoped advisory lock, not operational SQL data editing.
        await db.execute(select(func.pg_advisory_xact_lock(bundle.budget_scope_id.int % (2**63))))
        budget = await db.scalar(
            select(ConversationBudgetAccount)
            .where(ConversationBudgetAccount.scope_id == bundle.budget_scope_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if budget is None:
            try:
                cap_paise = bundle.budget_cap_paise
                snapshot = BudgetAccount(
                    str(bundle.budget_scope_id),
                    cap_paise,
                    BudgetCapApproval(
                        str(bundle.budget_scope_id),
                        bundle.budget_authorization_ref,
                        str(bundle.budget_owner_id),
                        cap_paise,
                        "0" * 64,
                        (
                            "Approved hosted provider project budget"
                            if cap_paise > 0
                            else "Approved zero-cost internal testing budget"
                        ),
                    ),
                )
            except ValueError:
                raise ConversationDenied("The approved project budget is invalid.") from None
            budget = ConversationBudgetAccount(
                scope_id=bundle.budget_scope_id,
                snapshot=snapshot.as_dict(),
                revision=1,
            )
            db.add(budget)
        else:
            previous = BudgetAccount.from_dict(budget.snapshot)
            if (
                previous.scope_id != str(bundle.budget_scope_id)
                or previous.cap_paise != bundle.budget_cap_paise
                or previous.cap_approval.approval_ref != bundle.budget_authorization_ref
                or previous.cap_approval.owner_actor_id != str(bundle.budget_owner_id)
            ):
                raise ConversationDenied("The approved shared testing budget does not match.")
        if isinstance(actor, ProcessingActor):
            # Public acquisition minutes belong to the append-only acquisition
            # ledger. The processing principal's empty canonical ledger is
            # enough for zero-entitlement provider stages; never mint a second
            # user grant for the same measured source. The shared budget still
            # needs to exist so a later paid provider plan can reserve against
            # its approved project cap.
            return
        approval = next(
            item
            for item in bundle.allowances
            if (item.tenant_id, item.person_id) == (actor.tenant_id, actor.person_id)
        )
        row = await db.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == actor.tenant_id,
                ConversationMinuteAccount.person_id == actor.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        before = (
            MinuteAccount(str(actor.tenant_id), str(actor.person_id))
            if row is None
            else MinuteAccount.from_dict(row.snapshot)
        )
        grant = MinuteGrant(
            str(actor.tenant_id),
            str(actor.person_id),
            str(approval.id),
            approval.seconds,
            approval.authorization_ref,
            str(approval.granted_by),
            approval.reason,
        )
        try:
            after = grant_minutes(before, grant)
        except ValueError:
            raise ConversationConflict("The immutable allowance approval changed.") from None
        if row is None:
            db.add(
                ConversationMinuteAccount(
                    tenant_id=actor.tenant_id,
                    person_id=actor.person_id,
                    snapshot=after.as_dict(),
                    revision=1,
                )
            )
        elif after != before:
            row.snapshot, row.revision = after.as_dict(), row.revision + 1
        await db.flush()
        intent = grant.as_dict()
        key = f"hosted-allowance:{approval.id}"
        if await app._replay(actor, key, "allowance_claimed", intent) is None:
            await app._receipt(
                actor,
                key,
                "allowance_claimed",
                intent,
                approval.id,
                app.clock(),
                resource_type="conversation_minute_account",
            )

    async def admit_upload(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        intent: IntakeIntent,
    ) -> None:
        bundle = await self.admit(app, actor)
        if intent.source_bytes > MAX_AUDIO_BYTES:
            raise ConversationDenied("Choose a recording up to 32 MB for this processing route.")
        if isinstance(actor, ProcessingActor):
            policy = bundle.acquisition_policy
            if policy is None or not policy.matches_actor(actor):
                raise ConversationDenied(
                    "This processing lease has no approved acquisition upload policy."
                )
            max_recordings = policy.max_recordings
            max_source_bytes = policy.max_source_bytes
            max_stored_source_bytes = policy.max_stored_source_bytes
        else:
            approval = next(
                item
                for item in bundle.allowances
                if (item.tenant_id, item.person_id) == (actor.tenant_id, actor.person_id)
            )
            max_recordings = approval.max_recordings
            max_source_bytes = approval.max_source_bytes
            max_stored_source_bytes = approval.max_stored_source_bytes
        # Reserve space by counting the immutable source-size registration in
        # the same transaction. Awaiting/deleting records still consume capacity.
        # This conservative global count protects a shared root across tenants.
        await app.database.execute(select(func.pg_advisory_xact_lock(725902, 1)))
        active = ConversationRecording.state != "deleted"
        total = await app.database.scalar(
            select(
                func.coalesce(
                    func.sum(ConversationRecording.source_bytes),
                    0,
                )
            ).where(active)
        )
        count, owner_bytes = (
            await app.database.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(ConversationRecording.source_bytes), 0),
                ).where(
                    active,
                    ConversationRecording.tenant_id == actor.tenant_id,
                    ConversationRecording.person_id == actor.person_id,
                )
            )
        ).one()
        if (
            intent.source_bytes > max_source_bytes
            or count >= max_recordings
            or owner_bytes + intent.source_bytes > max_stored_source_bytes
            or int(total or 0) + intent.source_bytes > bundle.max_stored_source_bytes
        ):
            raise ConversationConflict("The approved private recording capacity is full.")

    async def approval(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        recording: ConversationRecording,
        plan: ServicePlan,
        now: datetime,
        configuration_sha256: str | None = None,
    ) -> tuple[HostedApprovalBundle, StageApproval]:
        await require_execution_enabled(
            app.database,
            environment=self.environment,
            operations_tenant_id=self.operations_tenant_id,
        )
        bundle = self.current(now)
        self.recipient(bundle, actor)
        approved_default_configuration_sha256 = self._approved_default_configuration_sha256(
            bundle,
            actor,
            source_sha256=recording.source_sha256,
            stage=plan.checkpoint.stage,
        )
        configuration = await self._provider_configuration(
            app,
            configuration_sha256=configuration_sha256,
            default_configuration_sha256=approved_default_configuration_sha256,
        )
        if configuration is None:
            raise ConversationDenied("The approved provider configuration is unavailable.")
        if isinstance(actor, ProcessingActor):
            # Selecting the public template still requires the canonical exact
            # recording permission created by the intake consent command.
            await app._permission(actor, recording.permission_id, recording.source_sha256, now)
        approval = self.stage_approval(
            bundle,
            actor,
            source_sha256=recording.source_sha256,
            stage=plan.checkpoint.stage,
            configuration_sha256=configuration.configuration_sha256,
        )
        if approval is None or approval.expires_at_epoch <= int(now.timestamp()):
            raise ConversationDenied("This recording and processing stage need current approval.")
        if (
            plan.duration_ms > approval.max_source_duration_ms
            or (approval.stage == "C2" and recording.source_bytes > MAX_AUDIO_BYTES)
            or (recording.source_bytes if approval.stage == "C2" else len(plan.prepared.payload))
            > approval.max_input_bytes
            or (plan.prepared.max_completion_tokens or 0) > approval.max_completion_tokens
            or (
                content_hash(plan.profile)
                if hasattr(plan, "profile") and plan.profile is not None
                else None
            )
            != approval.profile_sha256
        ):
            raise ConversationDenied("This input exceeds the approved processing bounds.")
        await self.validate_route(
            app,
            actor,
            approval,
            bundle=bundle,
            task=plan.prepared.task,
            provider=plan.prepared.provider,
            model=plan.prepared.model,
            recipe=plan.recipe_revision,
            profile_revision=plan.prepared.profile_revision,
            configuration_sha256=configuration.configuration_sha256,
        )
        return bundle, approval

    async def _provider_configuration(
        self,
        app: ConversationApplication,
        *,
        configuration_sha256: str | None = None,
        default_configuration_sha256: str | None = None,
    ) -> ConversationProviderConfiguration | None:
        """Resolve the immutable route selected for a new or existing plan."""

        control_tenant_id = self.operations_tenant_id
        await lock_provider_configuration(app.database, control_tenant_id, shared=True)
        if configuration_sha256 is not None:
            value = await app.database.scalar(
                select(ConversationProviderConfiguration)
                .where(
                    ConversationProviderConfiguration.tenant_id == control_tenant_id,
                    ConversationProviderConfiguration.configuration_sha256 == configuration_sha256,
                )
                .order_by(ConversationProviderConfiguration.revision.desc())
                .limit(1)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            return value
        activation = await app.database.scalar(
            select(ConversationProviderActivation)
            .where(ConversationProviderActivation.tenant_id == control_tenant_id)
            .order_by(ConversationProviderActivation.sequence.desc())
            .limit(1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if activation is not None:
            selected = cast(
                ConversationProviderConfiguration | None,
                await app.database.scalar(
                    select(ConversationProviderConfiguration)
                    .where(
                        ConversationProviderConfiguration.id == activation.configuration_id,
                        ConversationProviderConfiguration.tenant_id == control_tenant_id,
                        ConversationProviderConfiguration.configuration_sha256
                        == activation.configuration_sha256,
                        ConversationProviderConfiguration.revision
                        == activation.configuration_revision,
                    )
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                ),
            )
            if selected is not None:
                return selected
            raise ConversationDenied("The active provider configuration is unavailable.")
        if default_configuration_sha256 is None:
            # A saved draft is not an activation. Without an exact digest
            # supplied by the release approval, fail closed instead of letting
            # the newest Admin row become an implicit provider route.
            return None
        value = await app.database.scalar(
            select(ConversationProviderConfiguration)
            .where(
                ConversationProviderConfiguration.tenant_id == control_tenant_id,
                ConversationProviderConfiguration.configuration_sha256
                == default_configuration_sha256,
            )
            .order_by(ConversationProviderConfiguration.revision.desc())
            .limit(1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return cast(ConversationProviderConfiguration | None, value)

    async def selected_asr_route(
        self, app: ConversationApplication
    ) -> tuple[str, str] | None:
        """Return the active approved ASR binding for a new transcription plan.

        A saved configuration is not enough to change routing.  Only the
        append-only activation row is eligible here; the later approval check
        still binds the route to the release approval and exact recording.
        """
        configuration = await self._provider_configuration(app)
        if configuration is None:
            return None
        try:
            config = parse_registry_config(configuration.configuration)
            if config.digest != configuration.configuration_sha256:
                raise ValueError
            route = next(item for item in config.routes if item.task == "asr")
            return route.provider_id, route.model_id
        except (ProviderRegistryError, StopIteration, TypeError, ValueError):
            raise ConversationDenied("The active provider configuration is invalid.") from None

    @staticmethod
    def _approved_default_configuration_sha256(
        bundle: HostedApprovalBundle,
        actor: ConversationActor,
        *,
        source_sha256: str,
        stage: str,
    ) -> str | None:
        """Return only the release-pinned default route digest.

        An unactivated saved configuration is deliberately not a default. The
        acquisition policy's base stages are the default for a processing
        lease; ordinary actors must have one unambiguous exact-source stage.
        """

        if isinstance(actor, ProcessingActor):
            policy = bundle.acquisition_policy
            if policy is None or not policy.matches_actor(actor):
                return None
            candidates = tuple(
                item.configuration_sha256 for item in policy.stages if item.stage == stage
            )
        else:
            candidates = tuple(
                item.configuration_sha256
                for item in bundle.stages
                if (
                    item.tenant_id,
                    item.person_id,
                    item.source_sha256,
                    item.stage,
                )
                == (actor.tenant_id, actor.person_id, source_sha256, stage)
            )
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def stage_approval(
        bundle: HostedApprovalBundle,
        actor: ConversationActor,
        *,
        source_sha256: str,
        stage: str,
        configuration_sha256: str | None = None,
    ) -> StageApproval | None:
        """Resolve one static or exact-source acquisition approval.

        Processing actors can use only the policy bound to the release's
        processing principal. Human actors can use only pre-issued exact-source
        stages; no caller-supplied provider or wildcard source is accepted.
        """

        if isinstance(actor, ProcessingActor):
            policy: AcquisitionProviderPolicy | None = bundle.acquisition_policy
            if policy is None or not policy.matches_actor(actor):
                return None
            try:
                derived = policy.derive_stage(
                    tenant_id=actor.tenant_id,
                    person_id=actor.person_id,
                    source_sha256=source_sha256,
                    stage=stage,  # type: ignore[arg-type]
                    configuration_sha256=configuration_sha256,
                )
                return derived
            except ValueError:
                return None
        candidates = tuple(
            item
            for item in bundle.stages
            if (
                item.tenant_id,
                item.person_id,
                item.source_sha256,
                item.stage,
                item.configuration_sha256 if configuration_sha256 is not None else None,
            )
            == (
                actor.tenant_id,
                actor.person_id,
                source_sha256,
                stage,
                configuration_sha256 if configuration_sha256 is not None else None,
            )
        )
        return candidates[0] if len(candidates) == 1 else None

    async def validate_route(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        approval: StageApproval,
        *,
        bundle: HostedApprovalBundle | None = None,
        task: str,
        provider: str,
        model: str,
        recipe: str,
        profile_revision: str | None,
        configuration_sha256: str | None = None,
    ) -> None:
        """Resolve a pinned future stage without inventing its as-yet unknown input."""
        assert actor.tenant_id is not None
        control_tenant_id = self.operations_tenant_id
        selected_digest = configuration_sha256 or approval.configuration_sha256
        selected = await self._provider_configuration(
            app,
            configuration_sha256=selected_digest,
        )
        if selected is None or selected.configuration_sha256 != approval.configuration_sha256:
            raise ConversationDenied("The current provider configuration is not approved.")
        # A persisted configuration cannot retain authority after its control
        # owner loses the verified identity or active operations membership.
        # This checks current authorization, not the historical browser session:
        # signing out normally does not erase a valid saved configuration.
        controller = await app.database.scalar(
            select(Person)
            .where(Person.id == selected.person_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        membership = await app.database.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == control_tenant_id,
                Membership.person_id == selected.person_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        control_tenant = await app.database.scalar(
            select(Tenant)
            .where(Tenant.id == control_tenant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            controller is None
            or controller.status != "active"
            or (controller.email or "").casefold() not in CONTROL_ACCOUNTS
            or controller.email_verified_at is None
            or membership is None
            or membership.status != "active"
            or membership.ended_at is not None
            or membership.role not in {"owner", "admin"}
            or control_tenant is None
            or control_tenant.status != "active"
        ):
            raise ConversationDenied("The provider control authorization is no longer active.")
        try:
            config = parse_registry_config(selected.configuration)
            if config.digest != approval.configuration_sha256:
                raise ValueError("configuration_changed")
            route = next(item for item in config.routes if item.task == task)
            dispatch = resolve_dispatch(
                config,
                DispatchRequest(
                    route.task,
                    config.revision,
                    config.digest,
                    approval.permission_ref,
                    route.required_input_stage,
                ),
            )
            provider_config = next(
                item
                for item in config.providers
                if (item.provider_id, item.model_id) == (dispatch.provider_id, dispatch.model_id)
            )
            for field in (
                "permission_ref",
                "provider_terms_ref",
                "privacy_ref",
                "pricing_ref",
                "free_allowance_ref",
                "credential_ref",
            ):
                if getattr(provider_config, field) != getattr(approval, field):
                    raise ValueError("approved_reference_changed")
            paid_dispatch = dispatch.max_cost_paise > 0
            if paid_dispatch:
                if (
                    bundle is None
                    or bundle.paid_approval_ref != config.policy.paid_approval_ref
                    or approval.zero_cost_basis != "paid_pricing_evidence"
                    or approval.max_cost_paise != dispatch.max_cost_paise
                ):
                    raise ValueError("paid_approval_changed")
            elif (
                approval.max_cost_paise != 0 or approval.zero_cost_basis == "paid_pricing_evidence"
            ):
                raise ValueError("free_approval_changed")
            if (
                (approval.provider_id, approval.model_id, approval.recipe_revision)
                != (provider, model, recipe)
                or (dispatch.provider_id, dispatch.model_id, dispatch.recipe_revision)
                != (approval.provider_id, approval.model_id, approval.recipe_revision)
                or (profile_revision is not None and route.profile_revision != profile_revision)
            ):
                raise ValueError("approved_route_changed")
        except (ValueError, TypeError, StopIteration):
            raise ConversationDenied(
                "The exact provider route and approval do not match."
            ) from None

    @staticmethod
    def authorization_ref(bundle: HostedApprovalBundle, approval: StageApproval) -> str:
        return f"hosted-stage-v1:{approval.id}:{bundle.digest}"

    async def validate_quote(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        recording: ConversationRecording,
        plan: ServicePlan,
        row: ConversationQuote,
        quote: Quote,
        permission: ExecutionPermission,
        now: datetime,
    ) -> StageApproval:
        configuration_sha256 = quote.provider_configuration_sha256
        bundle = self.current(now)
        if configuration_sha256 is None:
            configuration_sha256 = self._configuration_from_permission(
                bundle, actor, recording.source_sha256, plan.checkpoint.stage, permission
            )
        bundle, approval = await self.approval(
            app,
            actor,
            recording,
            plan,
            now,
            configuration_sha256=configuration_sha256,
        )
        # User minutes are charged once by the local C1 audio inspection. Hosted
        # provider stages use their own request/token/budget approvals and must
        # never charge the same source audio again.
        seconds = 0
        if (
            row.budget_scope_id != bundle.budget_scope_id
            or quote.max_cost_paise != approval.max_cost_paise
            or quote.provider_configuration_sha256 not in {None, approval.configuration_sha256}
            or quote.entitlement_seconds != seconds
            or permission.authorization_ref != self.authorization_ref(bundle, approval)
            or quote.expires_at_epoch > min(bundle.expires_at_epoch, approval.expires_at_epoch)
            or quote.privacy_revision != approval.privacy_revision
            or any(
                getattr(quote, field) != getattr(approval, field)
                for field in (
                    "permission_ref",
                    "provider_terms_ref",
                    "retention_ref",
                    "professional_gate_ref",
                    "pricing_ref",
                )
            )
        ):
            raise ConversationDenied("The exact quote is outside its current release approval.")
        # All admitted operations hold the current owner/session/recording locks.
        # The budget lock makes the finite provider-call allowance atomic with
        # reservation, even across multiple uploads of the same source.
        _, budget = await ConversationInference(app).accounts(recording, row)
        entries = BudgetAccount.from_dict(budget.snapshot).reservations
        prefix = f"hosted-stage-v1:{approval.id}:"
        used = [entry for entry in entries if entry.permission.authorization_ref.startswith(prefix)]
        already_reserved = any(entry.quote.quote_id == quote.quote_id for entry in used)
        cached = await app.database.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.recording_id == recording.id,
                ConversationInferenceTask.cache_key == plan.checkpoint.cache_key,
                ConversationInferenceTask.generation == recording.generation,
                ConversationInferenceTask.erased_at.is_(None),
            )
        )
        if len(used) > approval.max_requests or (
            len(used) >= approval.max_requests and not already_reserved and cached is None
        ):
            raise ConversationDenied("This recording's approved provider allowance is used.")
        return approval

    def _configuration_from_permission(
        self,
        bundle: HostedApprovalBundle,
        actor: ConversationActor,
        source_sha256: str,
        stage: str,
        permission: ExecutionPermission,
    ) -> str | None:
        prefix, separator, remainder = permission.authorization_ref.partition(":")
        if prefix != "hosted-stage-v1" or not separator:
            return None
        approval_id, separator, bundle_digest = remainder.partition(":")
        if not separator or not approval_id or not bundle_digest:
            return None
        if bundle_digest != bundle.digest:
            return None
        try:
            approval_uuid = UUID(approval_id)
        except ValueError:
            return None
        # Older exact-source quotes may omit the configuration digest. Resolve
        # their immutable approval id directly before asking current selection
        # to choose a route; switching future activation must not rewrite them.
        candidates = tuple(
            item
            for item in bundle.stages
            if (
                item.id == approval_uuid
                and item.tenant_id == actor.tenant_id
                and item.person_id == actor.person_id
                and item.source_sha256 == source_sha256
                and item.stage == stage
            )
        )
        if len(candidates) == 1:
            return candidates[0].configuration_sha256
        if isinstance(actor, ProcessingActor) and bundle.acquisition_policy is not None:
            policy = bundle.acquisition_policy
            for configuration_sha256 in policy.configuration_digests():
                try:
                    derived = policy.derive_stage(
                        tenant_id=actor.tenant_id,
                        person_id=actor.person_id,
                        source_sha256=source_sha256,
                        stage=stage,  # type: ignore[arg-type]
                        configuration_sha256=configuration_sha256,
                    )
                except ValueError:
                    continue
                if derived.id == approval_uuid:
                    return derived.configuration_sha256
        return None

    async def issue(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        recording_id: UUID,
        *,
        key: str,
        request: StageRequest | None = None,
    ) -> dict[str, Any]:
        now = await app.admit(actor)
        await app.get(actor, recording_id)
        recording = await app._recording(actor, recording_id)
        service = ConversationInference(app, authority=self)
        plan = (
            await service.plan_transcription(recording)
            if request is None
            else await ReportingPipeline(service).plan(recording, request)
        )
        bundle, approval = await self.approval(app, actor, recording, plan, now)
        intent = {
            "recording_id": str(recording_id),
            "cache_key": plan.checkpoint.cache_key,
            "authority_sha256": bundle.digest,
            "approval_id": str(approval.id),
            "configuration_sha256": approval.configuration_sha256,
        }
        replay = await app._replay(actor, key, "hosted_provider_quote", intent)
        if replay is not None and replay.result_id is not None:
            row, quote, permission = await service._quote(
                actor,
                recording,
                replay.result_id,
                plan,
                now,
                require_acceptance=False,
            )
        else:
            identifier = uuid4()
            quote = Quote(
                str(identifier),
                binding_for(recording),
                str(actor.person_id),
                str(bundle.budget_scope_id),
                approval.provider_id,
                approval.model_id,
                approval.recipe_revision,
                plan.prepared.operation,
                plan.prepared.input_sha256,
                approval.privacy_revision,
                approval.permission_ref,
                approval.provider_terms_ref,
                approval.retention_ref,
                approval.professional_gate_ref,
                approval.pricing_ref,
                0,
                approval.max_cost_paise,
                int(now.timestamp()),
                min(int(now.timestamp()) + 900, bundle.expires_at_epoch, approval.expires_at_epoch),
                approval.configuration_sha256,
            )
            permission = ExecutionPermission(
                self.authorization_ref(bundle, approval),
                quote.fingerprint,
                str(actor.person_id),
                quote.expires_at_epoch,
            )
            row = ConversationQuote(
                id=identifier,
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                recording_id=recording_id,
                budget_scope_id=bundle.budget_scope_id,
                quote=quote.as_dict(),
                execution_permission=permission.as_dict(),
            )
        await self.validate_quote(app, actor, recording, plan, row, quote, permission, now)
        minutes, budget = await service.accounts(recording, row)
        already = any(
            item.quote.quote_id == quote.quote_id
            for item in BudgetAccount.from_dict(budget.snapshot).reservations
        )
        cached = await app.database.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.recording_id == recording.id,
                ConversationInferenceTask.cache_key == plan.checkpoint.cache_key,
                ConversationInferenceTask.generation == recording.generation,
                ConversationInferenceTask.erased_at.is_(None),
            )
        )
        if not already and cached is None:
            try:
                reserve(
                    MinuteAccount.from_dict(minutes.snapshot),
                    BudgetAccount.from_dict(budget.snapshot),
                    str(uuid4()),
                    quote,
                    permission,
                    int(now.timestamp()),
                )
            except ValueError:
                raise ConversationConflict(
                    "The remaining approved processing allowance is unavailable."
                ) from None
        if replay is None:
            app.database.add(row)
            await app.database.flush()
            await app._receipt(actor, key, "hosted_provider_quote", intent, row.id, now)
        accepted = await app.database.get(ConversationQuoteAcceptance, row.id)
        if quote.max_cost_paise == 0:
            cost_label = "₹0 · approved allowance"
        else:
            cost_label = (
                f"up to ₹{quote.max_cost_paise // 100}."
                f"{quote.max_cost_paise % 100:02d} · approved project cap"
            )
        return {
            "id": str(row.id),
            "recording_id": str(recording.id),
            "stage": approval.stage,
            "provider": quote.provider_id,
            "model": quote.provider_model,
            "quote_fingerprint": quote.fingerprint,
            "privacy_revision": quote.privacy_revision,
            "privacy_notice": approval.privacy_notice,
            "cost_label": cost_label,
            "max_cost_paise": quote.max_cost_paise,
            "budget_cap_paise": bundle.budget_cap_paise,
            "entitlement_seconds": quote.entitlement_seconds,
            "input_sha256": quote.input_sha256,
            "expires_at_epoch": quote.expires_at_epoch,
            "accepted": accepted is not None
            and same_actor(accepted, actor)
            and (
                accepted.tenant_id,
                accepted.person_id,
                accepted.session_id,
                accepted.quote_fingerprint,
                accepted.privacy_revision,
            )
            == (
                actor.tenant_id,
                actor.person_id,
                actor.session_id,
                quote.fingerprint,
                quote.privacy_revision,
            ),
        }
