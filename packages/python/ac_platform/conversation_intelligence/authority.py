"""Release-composed allowance and exact provider quote authority.

An opaque reference in an admin form cannot activate processing. The deployment
must supply a separately approved, hash-pinned bundle. Its named source grants
must match the current admin registry. Quote issuance never accepts the quote.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderPolicy,
    HostedApprovalBundle,
    StageApproval,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    utc,
)
from ac_platform.conversation_intelligence.budget_admin import (
    ADMIN_BUDGET_CEILING_PAISE,
    is_admin_budget_approval_ref,
    is_any_admin_budget_approval_ref,
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
    effective_budget_cap_paise,
    reserve,
)
from ac_platform.conversation_intelligence.execution_control import require_execution_enabled
from ac_platform.conversation_intelligence.gemini_tasks import (
    GeminiTaskError,
    require_long_coaching_cost_approval,
)
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
)
from ac_platform.conversation_intelligence.inference import (
    INFERENCE_JOB,
    ConversationInference,
    ServicePlan,
    TranscriptionPlan,
    binding_for,
    verified_checkpoint,
)
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationProviderActivation,
    ConversationProviderConfiguration,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationRecording,
    ConversationRun,
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
from ac_platform.conversation_intelligence.reporting_pipeline import (
    ReportingPipeline,
    StagePlan,
    StageRequest,
)
from ac_platform.conversation_intelligence.stage_supplements import (
    StageSupplementContext,
    matches_stage_supplement,
    processing_plan_sha256,
    supplemental_reservations,
)
from ac_platform.identity.models import Person
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.outbox.repository import canonical_receipt_digest
from ac_platform.tenancy.models import Membership, Tenant

ApprovalLoader = Callable[[], HostedApprovalBundle]


def _budget_matches_release(previous: BudgetAccount, bundle: HostedApprovalBundle) -> bool:
    release_approval = (
        previous.cap_approval.approval_ref == bundle.budget_authorization_ref
        and previous.cap_approval.owner_actor_id == str(bundle.budget_owner_id)
    )
    admin_approval = (
        is_admin_budget_approval_ref(previous.cap_approval.approval_ref, bundle.digest)
        and previous.cap_paise <= ADMIN_BUDGET_CEILING_PAISE
    )
    carried_admin_approval = (
        is_any_admin_budget_approval_ref(previous.cap_approval.approval_ref)
        and previous.cap_approval.owner_actor_id == str(bundle.budget_owner_id)
        and previous.cap_paise <= ADMIN_BUDGET_CEILING_PAISE
    )
    try:
        effective_budget_cap_paise(bundle.budget_cap_paise, previous.cap_paise)
    except ValueError:
        return False
    # A release-bound budget may only continue when the persisted amount is
    # within the current release ceiling. Historical Admin approvals are
    # handled separately above and may carry a larger reserved snapshot; new
    # work is still bounded by ``effective_budget_cap_paise``.
    if release_approval and previous.cap_paise > bundle.budget_cap_paise:
        return False
    return previous.scope_id == str(bundle.budget_scope_id) and (
        release_approval or admin_approval or carried_admin_approval
    )


class ConversationAuthority:
    def __init__(
        self,
        loader: ApprovalLoader,
        *,
        environment: str,
        operations_tenant_id: UUID,
        tester_policy: InternalTesterPolicy | None = None,
    ) -> None:
        if not isinstance(operations_tenant_id, UUID):
            raise ValueError("hosted_operations_tenant_required")
        self.loader, self.environment = loader, environment
        self.operations_tenant_id = operations_tenant_id
        self.tester_policy = tester_policy

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
        if isinstance(actor, ProcessingActor) or any(
            item.tenant_id == actor.tenant_id and item.person_id == actor.person_id
            for item in bundle.allowances
        ):
            self.recipient(bundle, actor)
        else:
            tester = (
                None
                if self.tester_policy is None
                else await self.tester_policy.for_actor(
                    app.database, actor, "account_minutes", bundle=bundle
                )
            )
            if tester is None:
                raise ConversationDenied("This account has no approved processing allowance.")
        return bundle

    async def reconcile_existing_minute_account(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        *,
        bundle: HostedApprovalBundle,
    ) -> None:
        """Apply the current tester-derived flag before a hosted run reserves minutes.

        This only changes the derived unlimited flag on an existing account. A
        finite grant is still created by the explicit allowance claim command,
        while a revocation cannot leave an old unlimited flag active on a run
        that was already quoted.
        """

        if isinstance(actor, ProcessingActor) or actor.tenant_id is None:
            return
        tester = (
            None
            if self.tester_policy is None
            else await self.tester_policy.for_actor(
                app.database, actor, "account_minutes", bundle=bundle
            )
        )
        row = await app.database.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == actor.tenant_id,
                ConversationMinuteAccount.person_id == actor.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            return
        before = MinuteAccount.from_dict(row.snapshot)
        if before.unlimited == (tester is not None):
            return
        after = replace(before, unlimited=tester is not None)
        row.snapshot, row.revision = after.as_dict(), row.revision + 1
        await app.database.flush()

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
            if not _budget_matches_release(previous, bundle):
                raise ConversationDenied("The approved shared testing budget does not match.")
        if isinstance(actor, ProcessingActor):
            # Public acquisition minutes belong to the append-only acquisition
            # ledger. The processing principal's empty canonical ledger is
            # enough for zero-entitlement provider stages; never mint a second
            # user grant for the same measured source. The shared budget still
            # needs to exist so a later paid provider plan can reserve against
            # its approved project cap.
            return
        await self.reconcile_existing_minute_account(app, actor, bundle=bundle)
        tester = (
            None
            if self.tester_policy is None
            else await self.tester_policy.for_actor(db, actor, "account_minutes", bundle=bundle)
        )
        approval = next(
            (
                item
                for item in bundle.allowances
                if (item.tenant_id, item.person_id) == (actor.tenant_id, actor.person_id)
            ),
            None,
        )
        if approval is None and tester is None:
            raise ConversationDenied("This account has no approved processing allowance.")
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
        if tester is not None:
            after = replace(before, unlimited=True)
        else:
            assert approval is not None
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
                # A tester approval can be revoked or superseded by a finite
                # allowance.  Do not let the old derived flag survive that
                # transition and silently keep bypassing the finite grant. Add
                # the replacement grant in the same immutable construction so
                # an unlimited account with existing reservations does not
                # fail validation in an impossible intermediate state.
                existing = next(
                    (item for item in before.grants if item.grant_id == grant.grant_id),
                    None,
                )
                if existing is not None and existing != grant:
                    raise ValueError("immutable grant idempotency conflict")
                after = replace(
                    before,
                    unlimited=False,
                    grants=before.grants if existing is not None else (*before.grants, grant),
                )
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
        if tester is not None:
            intent = {
                "tester_approval_id": str(tester.id),
                "scope": "account_minutes",
                "policy_digest": bundle.digest,
            }
            key = f"hosted-tester-allowance:{tester.id}"
            result_id = tester.id
        else:
            assert approval is not None
            intent = grant.as_dict()
            key = f"hosted-allowance:{approval.id}"
            result_id = approval.id
        if await app._replay(actor, key, "allowance_claimed", intent) is None:
            await app._receipt(
                actor,
                key,
                "allowance_claimed",
                intent,
                result_id,
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
            tester = None
        else:
            approval = next(
                (
                    item
                    for item in bundle.allowances
                    if (item.tenant_id, item.person_id) == (actor.tenant_id, actor.person_id)
                ),
                None,
            )
            tester = (
                None
                if self.tester_policy is None
                else await self.tester_policy.for_actor(
                    app.database, actor, "analysis_count", bundle=bundle
                )
            )
            if approval is None:
                if tester is None:
                    raise ConversationDenied("This account has no approved processing allowance.")
                max_recordings = None
                max_source_bytes = MAX_AUDIO_BYTES
                max_stored_source_bytes = bundle.max_stored_source_bytes
            else:
                # A named tester's analysis_count scope bypasses the finite
                # recording count even when a legacy allowance is also bound
                # to the same account.  Keep that allowance's byte/storage
                # caps and all provider checks below.
                max_recordings = None if tester is not None else approval.max_recordings
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
            or (max_recordings is not None and count >= max_recordings)
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
        # Named testers may bypass the finite account allowance and recording
        # count, but they still need a current identity and the exact stage,
        # route, provider budget, and source permissions below.  Keep the
        # ordinary recipient check for every other actor.
        if (
            isinstance(actor, ProcessingActor)
            or any(
                item.tenant_id == actor.tenant_id and item.person_id == actor.person_id
                for item in bundle.allowances
            )
            or self.tester_policy is None
            or await self.tester_policy.for_actor(
                app.database, actor, "analysis_count", bundle=bundle
            )
            is None
        ):
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
        if approval.stage == "C5" and approval.provider_id == "gemini":
            try:
                require_long_coaching_cost_approval(
                    plan.prepared.as_provider_body(),
                    model=approval.model_id,
                    maximum=plan.prepared.max_completion_tokens or 0,
                    cost_basis=approval.zero_cost_basis,
                    cost_paise=approval.max_cost_paise,
                    pricing_ref=approval.pricing_ref,
                    price_evidence_sha256=approval.price_evidence_sha256,
                )
            except GeminiTaskError:
                raise ConversationDenied(
                    "The complete call needs a coaching quote within its approved cost limit."
                ) from None
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

    async def selected_asr_route(self, app: ConversationApplication) -> tuple[str, str] | None:
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
    async def _human_processing_owner(
        app: ConversationApplication,
        actor: ProcessingActor,
        recording: ConversationRecording,
        now: datetime,
    ) -> UUID | None:
        """Resolve the source owner through immutable usage and claim rows."""

        lease = await app.database.get(ConversationProcessingLease, actor.processing_lease_id)
        if (
            lease is None
            or lease.tenant_id != actor.tenant_id
            or lease.person_id != actor.person_id
            or lease.revoked_at is not None
        ):
            return None
        usage = await app.database.get(ConversationAcquisitionUsage, lease.usage_id)
        link = await app.database.scalar(
            select(ConversationGuestSubmission).where(
                ConversationGuestSubmission.tenant_id == actor.tenant_id,
                ConversationGuestSubmission.recording_id == recording.id,
                ConversationGuestSubmission.processing_lease_id == lease.id,
            )
        )
        if (
            usage is None
            or link is None
            or usage.tenant_id != actor.tenant_id
            or usage.id != lease.usage_id
            or usage.submission_id != link.submission_id
            or usage.source_sha256 != recording.source_sha256
            or link.usage_id != usage.id
            or link.person_id != actor.person_id
            or link.source_sha256 != recording.source_sha256
        ):
            return None
        if usage.visitor_id is None:
            owner_id = usage.person_id
        else:
            visitor = await app.database.get(ConversationVisitor, usage.visitor_id)
            claim = await app.database.get(ConversationVisitorClaim, usage.visitor_id)
            if (
                visitor is None
                or visitor.tenant_id != actor.tenant_id
                or visitor.revoked_at is not None
                or (claim is not None and claim.tenant_id != actor.tenant_id)
                or (claim is None and utc(visitor.expires_at) <= utc(now))
            ):
                return None
            owner_id = None if claim is None else claim.person_id
        if owner_id is None:
            return None
        person = await app.database.get(Person, owner_id)
        member = await app.database.get(Membership, (actor.tenant_id, owner_id))
        tenant = await app.database.get(Tenant, actor.tenant_id)
        if (
            person is None
            or person.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or tenant is None
            or tenant.status != "active"
        ):
            return None
        return owner_id

    async def _provider_stage_request_count_tester(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        recording: ConversationRecording,
        now: datetime,
        bundle: HostedApprovalBundle,
    ) -> bool:
        """Resolve the named request-count scope through the source owner.

        A processing lease is shared infrastructure, not tester identity. Its
        exemption is considered only after the immutable usage/submission and
        current claim rows resolve the recording to a verified human owner.
        """

        if self.tester_policy is None:
            return False
        if isinstance(actor, ProcessingActor):
            owner_id = await self._human_processing_owner(app, actor, recording, now)
            if owner_id is None:
                return False
            approval = await self.tester_policy.for_human_owner(
                app.database,
                tenant_id=recording.tenant_id,
                person_id=owner_id,
                scope="provider_stage_request_count",
                bundle=bundle,
            )
            return approval is not None
        return (
            await self.tester_policy.for_actor(
                app.database,
                actor,
                "provider_stage_request_count",
                bundle=bundle,
            )
        ) is not None

    @staticmethod
    async def _supplement_primary_input_sha256(
        app: ConversationApplication,
        actor: ProcessingActor,
        recording: ConversationRecording,
        plan: StagePlan,
        active_plan: ConversationProcessingPlan,
        bundle: HostedApprovalBundle,
        approval: StageApproval,
    ) -> str | None:
        """Bind repair to the exact primary C5 input admitted by this plan."""

        repair = plan.request.repair
        if repair is None:
            return plan.prepared.input_sha256
        original = await app.database.get(ConversationInferenceTask, repair.original_run_id)
        if (
            original is None
            or original.stage != "C5"
            or original.state != "uncertain"
            or original.erased_at is not None
            or not same_actor(original, actor)
            or original.recording_id != recording.id
            or original.generation != recording.generation
            or original.quote_id is None
            or original.intent is None
            or content_hash(original.intent) != original.intent_sha256
        ):
            return None
        request = original.intent.get("request")
        prepared = original.intent.get("input")
        if (
            not isinstance(request, dict)
            or request != plan.request.model_copy(update={"repair": None}).model_dump(mode="json")
            or not isinstance(prepared, dict)
        ):
            return None
        primary_input_sha256 = prepared.get("input_sha256")
        if (
            not isinstance(primary_input_sha256, str)
            or len(primary_input_sha256) != 64
            or any(character not in "0123456789abcdef" for character in primary_input_sha256)
        ):
            return None
        link = await app.database.get(ConversationPlanStageAuthorization, original.quote_id)
        quote_row = await app.database.get(ConversationQuote, original.quote_id)
        job = await app.database.get(Job, original.job_id)
        if (
            link is None
            or quote_row is None
            or job is None
            or link.plan_id != active_plan.id
            or link.cache_key != original.cache_key
            or quote_row.revoked_at is not None
            or quote_row.recording_id != recording.id
            or quote_row.tenant_id != recording.tenant_id
            or quote_row.person_id != actor.person_id
        ):
            return None
        try:
            quote = Quote.from_dict(quote_row.quote)
            permission = ExecutionPermission.from_dict(quote_row.execution_permission)
            from ac_platform.conversation_intelligence.processing_plan import c5_repair_intent

            traced_repair = c5_repair_intent(original, job)
        except (ConversationConflict, TypeError, ValueError, KeyError):
            return None
        if (
            link.quote_fingerprint != quote.fingerprint
            or original.input_sha256 != primary_input_sha256
            or quote.input_sha256 != primary_input_sha256
            or quote.quote_id != str(original.quote_id)
            or permission.quote_fingerprint != quote.fingerprint
            or permission.authorization_ref
            != ConversationAuthority.authorization_ref(bundle, approval)
            or traced_repair != repair
        ):
            return None
        return primary_input_sha256

    async def _matching_stage_supplement(
        self,
        app: ConversationApplication,
        actor: ConversationActor,
        recording: ConversationRecording,
        plan: ServicePlan,
        approval: StageApproval,
        bundle: HostedApprovalBundle,
        now: datetime,
    ) -> Any | None:
        if (
            not bundle.stage_call_supplements
            or not isinstance(actor, ProcessingActor)
            or not isinstance(plan, StagePlan)
            or plan.request.stage != "C5"
            or plan.request.coaching_prompt_revision != "coaching-v4"
            or plan.request.report_language not in {"en", "hi-Deva+en", "mr-Deva+en"}
        ):
            return None
        # A supplement is usable only inside the single currently accepted
        # processing plan. Its fingerprint excludes the release digest (which
        # pins the supplement itself) and time/session ephemera, while the
        # canonical consent helper separately validates those live bindings.
        from ac_platform.conversation_intelligence.processing_plan import (
            require_derived_input,
            require_plan_consent,
        )

        active_plans = (
            await app.database.scalars(
                select(ConversationProcessingPlan).where(
                    ConversationProcessingPlan.recording_id == recording.id,
                    ConversationProcessingPlan.tenant_id == actor.tenant_id,
                    ConversationProcessingPlan.person_id == actor.person_id,
                    ConversationProcessingPlan.state == "active",
                    ConversationProcessingPlan.erased_at.is_(None),
                )
            )
        ).all()
        if len(active_plans) != 1 or not same_actor(active_plans[0], actor):
            return None
        try:
            manifest = await require_plan_consent(app, actor, active_plans[0], self)
            require_derived_input(manifest, plan)
            current_plan_sha256 = processing_plan_sha256(manifest.as_dict())
        except ConversationDenied:
            return None
        owner_id = await self._human_processing_owner(app, actor, recording, now)
        if owner_id is None:
            return None
        primary_input_sha256 = await self._supplement_primary_input_sha256(
            app, actor, recording, plan, active_plans[0], bundle, approval
        )
        if primary_input_sha256 is None:
            return None
        context = StageSupplementContext(
            tenant_id=actor.tenant_id,
            processing_person_id=actor.person_id,
            owner_person_id=owner_id,
            source_sha256=recording.source_sha256,
            configuration_sha256=approval.configuration_sha256,
            stage="C5",
            recipe_revision=plan.recipe_revision,
            coaching_prompt_revision="coaching-v4",
            report_language=plan.request.report_language,
            processing_plan_sha256=current_plan_sha256,
            prepared_input_sha256=primary_input_sha256,
        )
        matching = tuple(
            item
            for item in bundle.stage_call_supplements
            if matches_stage_supplement(
                item,
                approval,
                context,
                now_epoch=int(utc(now).timestamp()),
            )
        )
        return matching[0] if len(matching) == 1 else None

    @staticmethod
    async def _completed_c2_cache_proof(
        app: ConversationApplication,
        actor: ConversationActor,
        recording: ConversationRecording,
        plan: ServicePlan,
        approval: StageApproval,
        cached: ConversationInferenceTask | None,
    ) -> bool:
        """Prove an exact completed C2 cache hit before exempting it from cap."""

        if (
            not isinstance(plan, TranscriptionPlan)
            or plan.checkpoint.stage != "C2"
            or cached is None
            or cached.stage != "C2"
            or cached.state != "completed"
            or cached.erased_at is not None
            or not same_actor(cached, actor)
            or cached.recording_id != recording.id
            or cached.tenant_id != recording.tenant_id
            or cached.person_id != recording.person_id
            or cached.generation != recording.generation
            or cached.cache_key != plan.checkpoint.cache_key
            or cached.input_sha256 != plan.prepared.input_sha256
            or cached.intent is None
            or content_hash(cached.intent) != cached.intent_sha256
            or cached.intent_sha256 != content_hash(plan.intent())
            or cached.checkpoint_id is None
        ):
            return False
        database = app.database
        run = await database.get(ConversationRun, cached.run_id)
        job = await database.get(Job, cached.job_id)
        checkpoint = await database.get(ConversationCheckpoint, cached.checkpoint_id)
        quote_row = await database.get(ConversationQuote, cached.quote_id)
        accepted = await database.get(ConversationQuoteAcceptance, cached.quote_id)
        if (
            run is None
            or job is None
            or checkpoint is None
            or quote_row is None
            or accepted is None
            or run.id != cached.run_id
            or run.job_id != cached.job_id
            or run.recording_id != recording.id
            or run.tenant_id != recording.tenant_id
            or run.person_id != recording.person_id
            or run.generation != recording.generation
            or run.recipe_revision != plan.recipe_revision
            or run.state != "completed"
            or run.completed_at is None
            or job.tenant_id != recording.tenant_id
            or job.kind != INFERENCE_JOB
            or job.dedupe_key != f"conversation:provider:{cached.run_id}"
            or job.payload != {"schema": 1, "run_id": str(cached.run_id)}
            or not job.external_side_effect
            or job.status != JobStatus.SUCCEEDED.value
            or job.dispatch_started_at is None
            or job.provider_idempotency_key != job.dedupe_key
            or job.provider_receipt is None
            or job.provider_receipt_digest is None
            or not isinstance(job.provider_receipt, dict)
            or quote_row.revoked_at is not None
            or quote_row.recording_id != recording.id
            or quote_row.tenant_id != recording.tenant_id
            or quote_row.person_id != recording.person_id
            or not same_actor(accepted, actor)
        ):
            return False
        try:
            receipt = job.provider_receipt
            if canonical_receipt_digest(receipt) != job.provider_receipt_digest:
                return False
            verified = verified_checkpoint(checkpoint, binding_for(recording))
            quote = Quote.from_dict(quote_row.quote)
            permission = ExecutionPermission.from_dict(quote_row.execution_permission)
        except (ConversationConflict, TypeError, ValueError, KeyError):
            return False
        approval_prefix = f"hosted-stage-v1:{approval.id}:"
        approval_digest = permission.authorization_ref.removeprefix(approval_prefix)
        response_sha256 = receipt.get("response_sha256")
        dispatch_epoch = int(utc(job.dispatch_started_at).timestamp())
        return (
            checkpoint.stage == "C2"
            and verified.cache_key == plan.checkpoint.cache_key
            and checkpoint.recording_id == recording.id
            and isinstance(checkpoint.payload, dict)
            and isinstance(response_sha256, str)
            and len(response_sha256) == 64
            and all(character in "0123456789abcdef" for character in response_sha256)
            and checkpoint.payload.get("revision") == response_sha256
            and checkpoint.payload.get("raw_response_sha256") == response_sha256
            and receipt.get("schema") == "ac.sales-xray.provider-receipt/1"
            and receipt.get("provider") == plan.prepared.provider
            and receipt.get("model") == plan.prepared.model
            and receipt.get("input_sha256") == plan.prepared.input_sha256
            and receipt.get("validation") == "transcript_schema_and_source_binding"
            and receipt.get("validation_state") == "validated"
            and receipt.get("human_approved") is False
            and receipt.get("raw_blob_id") == str(cached.run_id)
            and receipt.get("idempotency_key") == job.dedupe_key
            and receipt.get("checkpoint_id") == str(checkpoint.id)
            and receipt.get("checkpoint_manifest_sha256") == checkpoint.manifest_sha256
            and quote.quote_id == str(quote_row.id) == str(cached.quote_id)
            and quote.source == binding_for(recording)
            and quote.account_id == str(actor.person_id)
            and quote.budget_scope_id == str(quote_row.budget_scope_id)
            and quote.provider_id == plan.prepared.provider == approval.provider_id
            and quote.provider_model == plan.prepared.model == approval.model_id
            and quote.recipe_revision == plan.recipe_revision == approval.recipe_revision
            and quote.operation == plan.prepared.operation
            and quote.input_sha256 == plan.prepared.input_sha256
            and quote.entitlement_seconds == 0
            and quote.max_cost_paise == approval.max_cost_paise
            and quote.provider_configuration_sha256 == approval.configuration_sha256
            and quote.privacy_revision == approval.privacy_revision
            and quote.permission_ref == approval.permission_ref
            and quote.provider_terms_ref == approval.provider_terms_ref
            and quote.retention_ref == approval.retention_ref
            and quote.professional_gate_ref == approval.professional_gate_ref
            and quote.pricing_ref == approval.pricing_ref
            and permission.quote_fingerprint == quote.fingerprint
            and permission.approved_by == str(actor.person_id)
            and permission.expires_at_epoch == quote.expires_at_epoch
            and accepted.quote_fingerprint == quote.fingerprint
            and accepted.privacy_revision == quote.privacy_revision
            and permission.authorization_ref.startswith(approval_prefix)
            and approval_digest is not None
            and len(approval_digest) == 64
            and all(character in "0123456789abcdef" for character in approval_digest)
            and quote.created_at_epoch
            <= dispatch_epoch
            < min(quote.expires_at_epoch, permission.expires_at_epoch)
        )

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
        provider_count_tester = await self._provider_stage_request_count_tester(
            app, actor, recording, now, bundle
        )
        already_reserved = any(entry.quote.quote_id == quote.quote_id for entry in used)
        cached = await app.database.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.recording_id == recording.id,
                ConversationInferenceTask.cache_key == plan.checkpoint.cache_key,
                ConversationInferenceTask.generation == recording.generation,
                ConversationInferenceTask.erased_at.is_(None),
            )
        )
        supplement = await self._matching_stage_supplement(
            app, actor, recording, plan, approval, bundle, now
        )
        request_limit = approval.max_requests
        supplement_count = 0
        supplement_cost = 0
        if supplement is not None:
            request_limit += supplement.max_additional_requests
            try:
                supplement_count, supplement_cost = supplemental_reservations(
                    tuple(used), base_max_requests=approval.max_requests
                )
            except ValueError:
                raise ConversationDenied(
                    "This recording's approved provider allowance is used."
                ) from None
            if (
                supplement_count > supplement.max_additional_requests
                or supplement_cost > supplement.max_aggregate_cost_paise
                or quote.max_cost_paise > supplement.max_cost_per_request_paise
                or (
                    not already_reserved
                    and supplement_cost + quote.max_cost_paise > supplement.max_aggregate_cost_paise
                )
                or (not already_reserved and supplement_count >= supplement.max_additional_requests)
            ):
                raise ConversationDenied("This recording's approved provider allowance is used.")
        c2_cache_proven = False
        if (
            not provider_count_tester
            and approval.stage == "C2"
            and cached is not None
            and (len(used) > approval.max_requests or len(used) >= approval.max_requests)
        ):
            c2_cache_proven = await self._completed_c2_cache_proof(
                app, actor, recording, plan, approval, cached
            )
        exhausted = (
            False
            if provider_count_tester
            else (
                len(used) > request_limit
                or (
                    len(used) >= request_limit
                    and not already_reserved
                    and cached is None
                    and not c2_cache_proven
                )
            )
        )
        # Above the base allowance, only a fully verified completed C2 cache
        # hit can bypass the historical counter; it cannot reach dispatch.
        if (
            not provider_count_tester
            and approval.stage == "C2"
            and len(used) > approval.max_requests
        ):
            exhausted = not c2_cache_proven
        if exhausted:
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
        budget_snapshot = BudgetAccount.from_dict(budget.snapshot)
        already = any(
            item.quote.quote_id == quote.quote_id for item in budget_snapshot.reservations
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
                    budget_snapshot,
                    str(uuid4()),
                    quote,
                    permission,
                    int(now.timestamp()),
                    release_cap_paise=bundle.budget_cap_paise,
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
            "budget_cap_paise": budget_snapshot.cap_paise,
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
