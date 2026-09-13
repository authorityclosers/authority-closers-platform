"""Release-composed allowance and exact provider quote authority.

An opaque reference in an admin form cannot activate processing. The deployment
must supply a separately approved, hash-pinned bundle. Its named source grants
must match the current admin registry. Quote issuance never accepts the quote.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from ac_platform.conversation_intelligence.activation_contract import (
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
from ac_platform.conversation_intelligence.inference import (
    ConversationInference,
    ServicePlan,
    binding_for,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationProviderConfiguration,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.provider_admin import lock_provider_configuration
from ac_platform.conversation_intelligence.provider_registry import (
    DispatchRequest,
    parse_registry_config,
    resolve_dispatch,
)
from ac_platform.conversation_intelligence.providers import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline, StageRequest
from ac_platform.kernel.authz import ActorContext

ApprovalLoader = Callable[[], HostedApprovalBundle]


class ConversationAuthority:
    def __init__(self, loader: ApprovalLoader, *, environment: str) -> None:
        self.loader, self.environment = loader, environment

    def current(self, now: datetime) -> HostedApprovalBundle:
        try:
            # Never trust model_copy or mutable dictionaries supplied by a caller.
            bundle = HostedApprovalBundle.model_validate_json(self.loader().to_json())
            bundle.current(int(now.timestamp()), self.environment)
            if self.environment != "test" and any(
                item.zero_cost_basis == "synthetic" for item in bundle.stages
            ):
                raise ValueError("synthetic_approval_not_hosted")
            return bundle
        except (ValueError, TypeError, OSError):
            raise ConversationDenied(
                "The approved processing configuration is unavailable."
            ) from None

    def recipient(self, bundle: HostedApprovalBundle, actor: ActorContext) -> None:
        if not any(
            item.tenant_id == actor.tenant_id and item.person_id == actor.person_id
            for item in bundle.allowances
        ):
            raise ConversationDenied("This account has no approved processing allowance.")

    async def admit(
        self, app: ConversationApplication, actor: ActorContext
    ) -> HostedApprovalBundle:
        bundle = self.current(await app.admit(actor))
        self.recipient(bundle, actor)
        return bundle

    async def claim_allowance(self, app: ConversationApplication, actor: ActorContext) -> None:
        """POST-only application command; finite grants are never inferred from login."""
        bundle = await self.admit(app, actor)
        approval = next(
            item
            for item in bundle.allowances
            if (item.tenant_id, item.person_id) == (actor.tenant_id, actor.person_id)
        )
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
            snapshot = BudgetAccount(
                str(bundle.budget_scope_id),
                0,
                BudgetCapApproval(
                    str(bundle.budget_scope_id),
                    bundle.budget_authorization_ref,
                    str(bundle.budget_owner_id),
                    0,
                    "0" * 64,
                    "Approved zero-cost internal testing budget",
                ),
            )
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
                or previous.cap_paise != 0
                or previous.cap_approval.approval_ref != bundle.budget_authorization_ref
                or previous.cap_approval.owner_actor_id != str(bundle.budget_owner_id)
            ):
                raise ConversationDenied("The approved shared testing budget does not match.")
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
        actor: ActorContext,
        intent: IntakeIntent,
    ) -> None:
        bundle = await self.admit(app, actor)
        approval = next(
            item
            for item in bundle.allowances
            if (item.tenant_id, item.person_id) == (actor.tenant_id, actor.person_id)
        )
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
            intent.source_bytes > approval.max_source_bytes
            or count >= approval.max_recordings
            or owner_bytes + intent.source_bytes > approval.max_stored_source_bytes
            or int(total or 0) + intent.source_bytes > bundle.max_stored_source_bytes
        ):
            raise ConversationConflict("The approved private recording capacity is full.")

    async def approval(
        self,
        app: ConversationApplication,
        actor: ActorContext,
        recording: ConversationRecording,
        plan: ServicePlan,
        now: datetime,
    ) -> tuple[HostedApprovalBundle, StageApproval]:
        bundle = self.current(now)
        self.recipient(bundle, actor)
        approval = next(
            (
                item
                for item in bundle.stages
                if (item.tenant_id, item.person_id, item.source_sha256, item.stage)
                == (
                    actor.tenant_id,
                    actor.person_id,
                    recording.source_sha256,
                    plan.checkpoint.stage,
                )
            ),
            None,
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
            raise ConversationDenied("This input exceeds the approved free processing bounds.")
        assert actor.tenant_id is not None
        await lock_provider_configuration(app.database, actor.tenant_id, shared=True)
        latest = await app.database.scalar(
            select(ConversationProviderConfiguration)
            .where(ConversationProviderConfiguration.tenant_id == actor.tenant_id)
            .order_by(ConversationProviderConfiguration.revision.desc())
            .limit(1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if latest is None or latest.configuration_sha256 != approval.configuration_sha256:
            raise ConversationDenied("The current provider configuration is not approved.")
        try:
            config = parse_registry_config(latest.configuration)
            if config.digest != approval.configuration_sha256 or config.policy.allow_paid:
                raise ValueError("configuration_changed")
            route = next(item for item in config.routes if item.task == plan.prepared.task)
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
            provider = next(
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
                if getattr(provider, field) != getattr(approval, field):
                    raise ValueError("approved_reference_changed")
            if (
                (approval.provider_id, approval.model_id, approval.recipe_revision)
                != (plan.prepared.provider, plan.prepared.model, plan.recipe_revision)
                or (dispatch.provider_id, dispatch.model_id, dispatch.recipe_revision)
                != (approval.provider_id, approval.model_id, approval.recipe_revision)
                or dispatch.max_cost_paise != 0
                or (
                    plan.prepared.profile_revision is not None
                    and route.profile_revision != plan.prepared.profile_revision
                )
            ):
                raise ValueError("approved_route_changed")
        except (ValueError, TypeError, StopIteration):
            raise ConversationDenied(
                "The exact provider route and approval do not match."
            ) from None
        return bundle, approval

    @staticmethod
    def authorization_ref(bundle: HostedApprovalBundle, approval: StageApproval) -> str:
        return f"hosted-stage-v1:{approval.id}:{bundle.digest}"

    async def validate_quote(
        self,
        app: ConversationApplication,
        actor: ActorContext,
        recording: ConversationRecording,
        plan: ServicePlan,
        row: ConversationQuote,
        quote: Quote,
        permission: ExecutionPermission,
        now: datetime,
    ) -> StageApproval:
        bundle, approval = await self.approval(app, actor, recording, plan, now)
        seconds = (
            (plan.duration_ms + 999) // 1000
            if approval.stage == "C2"
            else approval.entitlement_seconds
        )
        if (
            row.budget_scope_id != bundle.budget_scope_id
            or quote.max_cost_paise != 0
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

    async def issue(
        self,
        app: ConversationApplication,
        actor: ActorContext,
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
                (plan.duration_ms + 999) // 1000
                if approval.stage == "C2"
                else int(approval.entitlement_seconds or 0),
                0,
                int(now.timestamp()),
                min(int(now.timestamp()) + 900, bundle.expires_at_epoch, approval.expires_at_epoch),
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
        return {
            "id": str(row.id),
            "recording_id": str(recording.id),
            "stage": approval.stage,
            "provider": quote.provider_id,
            "model": quote.provider_model,
            "quote_fingerprint": quote.fingerprint,
            "privacy_revision": quote.privacy_revision,
            "privacy_notice": approval.privacy_notice,
            "cost_label": "₹0 · approved allowance",
            "max_cost_paise": 0,
            "entitlement_seconds": quote.entitlement_seconds,
            "input_sha256": quote.input_sha256,
            "expires_at_epoch": quote.expires_at_epoch,
            "accepted": accepted is not None
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
