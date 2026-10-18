"""Source-bound acquisition admission into canonical intake and durable jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_source import MeasuredUpload
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingPrincipal
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.signals import MAX_SECONDS
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Organisation

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime


# Names shown in the upload terms for the provider ids an approval can seal.
AI_PROCESSOR_NAMES = {
    "deepgram": "Deepgram",
    "elevenlabs": "ElevenLabs",
    "gemini": "Google Gemini",
    "groq": "Groq",
    "openai": "OpenAI",
}


def _processor_names(policy: IntakePolicy) -> str:
    names = sorted({AI_PROCESSOR_NAMES.get(item, item) for item in policy.ai_processors})
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def upload_policy(policy: IntakePolicy) -> dict[str, Any]:
    """The exact upload terms a person accepts; its hash is recorded with each upload."""

    named = _processor_names(policy) if policy.ai_processors else ""
    processing = (
        f"then sends the recording and its transcript to its AI service providers, {named}, "
        "to transcribe the call and prepare and score your coaching report. "
        if named
        else "then uses its AI service providers to transcribe the recording and prepare "
        "your coaching report. "
    )
    if policy.keeps_until_deleted:
        kept = "Your recording and report are kept privately until you delete them. "
        kept_detail = (
            "AC keeps your recording, transcript and report privately until you delete "
            "the call or ask us to delete it."
        )
    elif policy.keeps_for_training:
        kept = (
            "Your recording and report are kept privately to improve AC's coaching AI "
            "until you delete them. "
        )
        kept_detail = (
            "AC keeps your recording, transcript and report privately to improve its "
            "coaching AI until you delete them."
        )
    else:
        kept = f"Your recording and report stay private for up to {policy.retention_days} days. "
        kept_detail = (
            "AC keeps your recording, transcript and report privately for up to "
            f"{policy.retention_days} days, then deletes them."
        )
    view: dict[str, Any] = {
        "schema": "ac.sales-xray.private-upload-consent/1",
        "privacy_revision": policy.privacy_revision,
        "recipe_revision": policy.acoustic_recipe,
        "maximum_file_bytes": MAX_AUDIO_BYTES,
        "maximum_call_seconds": MAX_SECONDS,
        "max_cost_paise": 0,
        "retention_days": policy.retention_days,
        "retention_mode": policy.retention_mode,
        "title": "Upload your call and get your report",
        "description": (
            "Upload only a call you have permission to analyse. AC checks its length, "
            + processing
            + "The call's length comes off your displayed allowance only when its report is "
            "ready; a call that fails uses none. You will not be charged a payment. "
            + kept
            + "You can request deletion at admin@authorityclosers.com. "
            "Review the privacy details before starting your analysis."
        ),
        "privacy_details": (
            (
                f"{named} receive the recording or its transcript only to transcribe the "
                "call and prepare and score your report. "
                if named
                else "Approved service providers may process this recording to prepare the "
                "transcript and coaching report. "
            )
            + kept_detail
            + " You can request deletion from Privacy & support."
        ),
    }
    return {**view, "policy_sha256": content_hash(view)}


class AcquisitionProcessing:
    def __init__(self, ownership: GuestOwnership, runtime: ConversationIntakeRuntime) -> None:
        self.ownership, self.runtime = ownership, runtime
        self.sessions, self.database = ownership.sessions, ownership.database
        self.application = ConversationApplication(self.database, clock=ownership.clock)

    async def prepare(
        self,
        upload: MeasuredUpload,
        *,
        policy_sha256: str,
        token: str | None = None,
        actor: ActorContext | None = None,
    ) -> tuple[ProcessingActor, dict[str, Any]]:
        from ac_platform.conversation_intelligence.application import ConversationConflict

        if policy_sha256 != upload_policy(self.runtime.policy)["policy_sha256"]:
            raise ConversationConflict("The upload terms changed. Review them and try again.")
        usage_id = await self.sessions.reserve(upload.source, token=token, actor=actor)
        # Reserve already fences the real owner and serializes tenant admission.
        # First use creates the same non-login principal/empty ledger as the
        # existing operator path, inside this upload's transaction.
        authority = self.runtime.authority
        if (
            actor is not None
            and authority is not None
            and self.runtime.policy.registered_organisations
        ):
            organisation = await self.database.scalar(
                select(Organisation.tenant_id).where(Organisation.tenant_id == actor.tenant_id)
            )
            if organisation is not None and organisation != authority.operations_tenant_id:
                bundle = authority.current(self.ownership.clock())
                principal = await self.database.scalar(
                    select(ConversationProcessingPrincipal).where(
                        ConversationProcessingPrincipal.tenant_id == organisation
                    )
                )
                policy = bundle.acquisition_policy_for(
                    organisation,
                    registered_organisation=True,
                    processing_person_id=None if principal is None else principal.person_id,
                )
                if policy is not None:
                    await self.ownership.provision(
                        operator_reference="ref:approval:AUT-1701:AUT-1694:all-organisations",
                        reason="Owner-approved default organisation processing on first upload.",
                        processing_person_id=policy.processing_person_id,
                    )
        processing = await self.ownership.resolve_processing_actor(
            upload.source.submission_id, token=token, actor=actor
        )
        intake = self.runtime.intake(self.application)
        quote = await intake.prepare(
            processing, upload.intent, key=f"acquisition-intake:{upload.source.submission_id}"
        )
        # The explicit upload action accepted this policy for these original
        # bytes. The UI can carry this upload's affirmative processing choice
        # into a separate exact provider-plan acceptance action. That action is
        # never accepted here; both receipts stay bound to the measured source.
        consent_key = f"acquisition-consent:{upload.source.submission_id}"
        consent_action = "acquisition_private_upload_consent"
        consent = {
            "policy_sha256": policy_sha256,
            "source_sha256": upload.source.source_sha256,
            "source_bytes": upload.intent.source_bytes,
            "duration_evidence_sha256": upload.source.duration_evidence_sha256,
            "usage_id": str(usage_id),
        }
        if await self.application._replay(processing, consent_key, consent_action, consent) is None:
            await self.application._receipt(
                processing,
                consent_key,
                consent_action,
                consent,
                UUID(quote["id"]),
                self.ownership.clock(),
            )
        await intake.accept(
            processing,
            UUID(quote["id"]),
            QuoteAcceptance(
                quote_fingerprint=quote["quote_fingerprint"],
                privacy_revision=quote["privacy_revision"],
                accepted=True,
            ),
        )
        return processing, quote

    async def enqueue(self, processing: ProcessingActor, quote: dict[str, Any]) -> dict[str, Any]:
        run = await self.application.request_run(
            processing,
            RunIntent(
                recording_id=UUID(quote["recording_id"]),
                source_revision=quote["source_revision"],
                quote_id=UUID(quote["id"]),
                recipe_revision=quote["recipe_revision"],
            ),
            key=f"acquisition-local-run:{quote['recording_id']}",
        )
        return {"recording_id": quote["recording_id"], "state": run["state"]}
