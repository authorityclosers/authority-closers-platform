"""Source-bound acquisition admission into canonical intake and durable jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from ac_platform.conversation_intelligence.acquisition_source import MeasuredUpload
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.intake import PRIVACY_REVISION, IntakePolicy
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.kernel.authz import ActorContext

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime


def upload_policy(policy: IntakePolicy) -> dict[str, Any]:
    view: dict[str, Any] = {
        "schema": "ac.sales-xray.private-upload-consent/1",
        "privacy_revision": PRIVACY_REVISION,
        "recipe_revision": policy.acoustic_recipe,
        "maximum_file_bytes": MAX_AUDIO_BYTES,
        "maximum_call_seconds": 1800,
        "max_cost_paise": 0,
        "retention_days": policy.retention_days,
        "title": "Upload your call and get your report",
        "description": (
            "Upload only a call you have permission to analyse. AC checks its length, "
            "then uses its AI service providers to transcribe the recording and prepare "
            "your coaching report. The call uses its length from your displayed free "
            "allowance once; you will not be charged a payment. "
            f"Your recording and report stay private for up to {policy.retention_days} days. "
            "You can request deletion at admin@authorityclosers.com. "
            "Review the privacy details before starting your analysis."
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
