"""Server-issued local intake quotes, exact consent and current AC entitlements.

The UI cannot activate a provider, grant itself minutes, or choose a budget scope.
This initial runtime admits the tested offline recipe only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    utc,
)
from ac_platform.conversation_intelligence.checkpoints import SourceBinding, require_text
from ac_platform.conversation_intelligence.contracts import (
    IntakeIntent,
    QuoteAcceptance,
    RecordingIntent,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
    reserve,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationQuote,
    ConversationQuoteAcceptance,
)
from ac_platform.kernel.authz import ActorContext

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.authority import ConversationAuthority

PRIVACY_REVISION = "local-private-audio-v1"
CONSENT_PREFIX = "intake-consent-v1:"


@dataclass(frozen=True)
class IntakePolicy:
    budget_scope_id: UUID
    tenant_ids: frozenset[UUID]
    authorization_ref: str
    retention_ref: str
    retention_days: int = 7

    def __post_init__(self) -> None:
        if (
            type(self.budget_scope_id) is not UUID
            or not self.tenant_ids
            or type(self.tenant_ids) is not frozenset
            or any(type(value) is not UUID for value in self.tenant_ids)
            or type(self.retention_days) is not int
            or not 1 <= self.retention_days <= 7
        ):
            raise ValueError("An exact internal workspace and bounded retention are required.")
        require_text(self.authorization_ref, "intake authorization")
        require_text(self.retention_ref, "retention reference")


class ConversationIntake:
    def __init__(
        self,
        application: ConversationApplication,
        policy: IntakePolicy,
        *,
        authority: ConversationAuthority | None = None,
    ) -> None:
        self.application, self.policy = application, policy
        self.database = application.database
        self.authority = authority

    async def admit(self, actor: ActorContext) -> None:
        await self.application.admit(actor)
        if actor.tenant_id not in self.policy.tenant_ids:
            raise ConversationDenied("Analysis has not been enabled for this workspace.")
        if self.authority is not None:
            bundle = await self.authority.admit(self.application, actor)
            if (
                bundle.budget_scope_id != self.policy.budget_scope_id
                or bundle.intake_authorization_ref != self.policy.authorization_ref
                or bundle.intake_retention_ref != self.policy.retention_ref
                or bundle.retention_days != self.policy.retention_days
            ):
                raise ConversationDenied("The approved private intake configuration changed.")

    async def _quote(self, actor: ActorContext, identifier: UUID) -> ConversationQuote:
        await self.admit(actor)
        row = await self.database.scalar(
            select(ConversationQuote)
            .where(
                ConversationQuote.id == identifier,
                ConversationQuote.tenant_id == actor.tenant_id,
                ConversationQuote.person_id == actor.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.revoked_at is not None:
            raise ConversationDenied("This analysis quote is unavailable.")
        quote = Quote.from_dict(row.quote)
        now = utc(self.application.clock())
        if quote.expires_at_epoch <= now.timestamp():
            raise ConversationConflict("The quote expired. Prepare this call again.")
        await self.application.get(actor, row.recording_id)
        return row

    def _view(self, row: ConversationQuote) -> dict[str, Any]:
        quote = Quote.from_dict(row.quote)
        return {
            "id": str(row.id),
            "recording_id": str(row.recording_id),
            "source_revision": quote.source.source_revision,
            "recipe_revision": quote.recipe_revision,
            "quote_fingerprint": quote.fingerprint,
            "privacy_revision": quote.privacy_revision,
            "cost_label": "₹0 · local audio measurements",
            "privacy_summary": (
                f"Your recording stays in AC's private storage for up to "
                f"{self.policy.retention_days} days, or until you delete it. "
                "This step does not send audio to an AI provider. "
                "A sales report needs a separate approved transcription and coaching run."
            ),
            "providers": ["AC local AudioAtlas"],
            "output_kind": "measurements",
            "expires_at": quote.expires_at_epoch,
        }

    async def prepare(
        self, actor: ActorContext, intent: IntakeIntent, *, key: str
    ) -> dict[str, Any]:
        await self.admit(actor)
        now = utc(self.application.clock())
        if self.authority is not None:
            await self.authority.claim_allowance(self.application, actor)
        payload = intent.model_dump(mode="json")
        replay = await self.application._replay(actor, key, "intake_quote", payload)
        if replay is not None and replay.result_id is not None:
            return self._view(await self._quote(actor, replay.result_id))
        if self.authority is not None:
            await self.authority.admit_upload(self.application, actor, intent)

        # An approved server allowance must exist before recording registration.
        # Preview reserve is pure; final reservation remains atomic with job enqueue.
        budget = await self.database.scalar(
            select(ConversationBudgetAccount)
            .where(ConversationBudgetAccount.scope_id == self.policy.budget_scope_id)
            .with_for_update()
        )
        minutes = await self.database.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == actor.tenant_id,
                ConversationMinuteAccount.person_id == actor.person_id,
            )
            .with_for_update()
        )
        if budget is None or minutes is None:
            raise ConversationDenied("Your workspace needs a processing allowance.")

        identifier, permission_id = uuid4(), uuid4()
        permission = ConversationPermission(
            id=permission_id,
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            source_sha256=intent.source_sha256,
            provider="local",
            permission_reference=CONSENT_PREFIX + str(identifier),
            retention_reference=self.policy.retention_ref,
            created_at=now,
            expires_at=now + timedelta(days=self.policy.retention_days),
            retention_until=now + timedelta(days=self.policy.retention_days),
        )
        self.database.add(permission)
        await self.database.flush()
        # Internal registration has a separate stable key; the caller's key has
        # already been checked and locked through the current AC person/session.
        recording = await self.application.register(
            actor,
            RecordingIntent(
                **{k: v for k, v in payload.items() if k != "duration_ms"},
                permission_reference=permission_id,
            ),
            key=f"intake-register:{identifier}",
        )
        quote = Quote(
            str(identifier),
            SourceBinding(str(actor.tenant_id), recording["id"], intent.source_sha256, "1"),
            str(actor.person_id),
            str(self.policy.budget_scope_id),
            "local",
            "audioatlas",
            AUDIOATLAS_RECIPE,
            "inspect_audioatlas",
            intent.source_sha256,
            PRIVACY_REVISION,
            CONSENT_PREFIX + str(identifier),
            "local-no-provider",
            self.policy.retention_ref,
            self.policy.authorization_ref,
            "local-zero-cost-v1",
            (intent.duration_ms + 999) // 1000,
            0,
            int(now.timestamp()),
            int((now + timedelta(minutes=30)).timestamp()),
        )
        execution = ExecutionPermission(
            quote.permission_ref, quote.fingerprint, str(actor.person_id), quote.expires_at_epoch
        )
        try:
            reserve(
                MinuteAccount.from_dict(minutes.snapshot),
                BudgetAccount.from_dict(budget.snapshot),
                str(uuid4()),
                quote,
                execution,
                int(now.timestamp()),
            )
        except ValueError:
            raise ConversationConflict(
                "The call exceeds your available processing allowance."
            ) from None
        row = ConversationQuote(
            id=identifier,
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            recording_id=UUID(recording["id"]),
            budget_scope_id=self.policy.budget_scope_id,
            quote=quote.as_dict(),
            execution_permission=execution.as_dict(),
        )
        self.database.add(row)
        await self.database.flush()
        await self.application._receipt(actor, key, "intake_quote", payload, identifier, now)
        return self._view(row)

    async def accept(
        self, actor: ActorContext, identifier: UUID, intent: QuoteAcceptance
    ) -> dict[str, Any]:
        row = await self._quote(actor, identifier)
        quote = Quote.from_dict(row.quote)
        if (
            intent.accepted is not True
            or intent.quote_fingerprint != quote.fingerprint
            or intent.privacy_revision != quote.privacy_revision
        ):
            raise ConversationConflict("Approve the exact current quote and privacy terms.")
        existing = await self.database.get(ConversationQuoteAcceptance, identifier)
        if existing is None:
            now = utc(self.application.clock())
            self.database.add(
                ConversationQuoteAcceptance(
                    quote_id=identifier,
                    tenant_id=actor.tenant_id,
                    person_id=actor.person_id,
                    session_id=actor.session_id,
                    quote_fingerprint=quote.fingerprint,
                    privacy_revision=quote.privacy_revision,
                    accepted_at=now,
                )
            )
            await self.database.flush()
            await self.application._receipt(
                actor,
                f"intake-accept:{identifier}",
                "quote_accepted",
                intent.model_dump(mode="json"),
                identifier,
                now,
            )
        elif (
            existing.person_id != actor.person_id
            or existing.tenant_id != actor.tenant_id
            or existing.session_id != actor.session_id
            or existing.quote_fingerprint != quote.fingerprint
            or existing.privacy_revision != quote.privacy_revision
        ):
            raise ConversationDenied("This approval does not belong to the current session.")
        return {"id": str(identifier), "state": "accepted"}

    async def require_accepted(
        self, actor: ActorContext, recording_id: UUID, quote_id: UUID
    ) -> dict[str, Any]:
        row = await self._quote(actor, quote_id)
        if row.recording_id != recording_id:
            raise ConversationDenied("The quote does not belong to this recording.")
        await require_intake_acceptance(self.application, actor, row)
        return await self.application.get(actor, recording_id)


async def require_intake_acceptance(
    application: ConversationApplication, actor: ActorContext, row: ConversationQuote
) -> None:
    quote = Quote.from_dict(row.quote)
    if not quote.permission_ref.startswith(CONSENT_PREFIX):
        return  # Existing separately authorized offline command contract.
    accepted = await application.database.get(ConversationQuoteAcceptance, row.id)
    if (
        accepted is None
        or accepted.tenant_id != actor.tenant_id
        or accepted.person_id != actor.person_id
        or accepted.session_id != actor.session_id
        or accepted.quote_fingerprint != quote.fingerprint
        or accepted.privacy_revision != quote.privacy_revision
    ):
        raise ConversationDenied("Approve this recording's quote before upload or processing.")
