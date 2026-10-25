"""Fill the AI-directory reviewer's fictional calls with their call facts, from the authored
fictional data, without any AI (approved data change, AUT-2222).

Owner, 25 Oct 2026 (through the orchestrator): the reviewer's organisation holds "a few
fictional analysed calls whose call facts are filled in". Its calls came from the synthetic
publication (``load-sales-xray-sandbox-hosted.py --target-name``), and the call data engine never
sends a sandbox organisation to a model (the AI spend policy). So the facts come from the
publication's own authored answer keys (prospect facts, each with its transcript quote) and go
through the engine's own path:
  1. each authored fact becomes a candidate in the engine's answer shape, and
     ``extraction.validate_response`` checks it like a model's answer (the value by the
     taxonomy's rules, the evidence as the call's own transcript lines);
  2. one fast-pipeline run per call, recorded as provider "authored" at no cost (a 'running'
     row, then its 'succeeded' row), and ``engine.save_objects`` stores the facts;
  3. one audit event naming the approver and the issue.
Only the named sandbox organisation is accepted. A call that already has call data is left as
it is, so a rerun changes nothing. Dry run by default (one transaction, rolled back).

Run inside the API container with the deployed settings:
    docker exec -i <api> sh -c 'cat > /tmp/drf.py' < directory-reviewer-facts.py
    docker exec <api> python /tmp/drf.py /tmp/drf.json /tmp/drf-facts.json [--apply]
input: {"command_id", "tenant_id", "org_name", "approver_email", "issue"}; facts: the
publication's answer keys' ``prospect_information.facts`` by call key (fictional content).
Prints call keys, fact types and counts only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.call_data import engine, extraction, policy, taxonomy
from ac_platform.call_data.models import CallDataRun, CallObject
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import (
    ConversationRecording,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Tenant

ACTION: Final = "call_data.authored_facts_data_change"
CREATED_BY: Final = "operator:directory-reviewer"
PROVIDER: Final = "authored"
MODEL: Final = "synthetic-answer-key/1"
LABEL_PREFIX: Final = "Synthetic · "
CONFIDENCE: Final = 0.9
MAX_TEXT: Final = 280


def _short(value: object) -> str:
    """One line of authored text, cut on a word if long."""
    text = " ".join(str(value).split())
    if len(text) <= MAX_TEXT:
        return text
    return text[: MAX_TEXT - 1].rsplit(" ", 1)[0] + "…"


def _budget(value: object) -> dict[str, Any]:
    amount = int(Decimal(str(value)))
    return {
        "upper": str(amount),
        "interval_shape": "upper_bound",
        "currency_code": "INR",
        "text": f"Up to Rs {amount:,}",
    }


# Authored prospect facts and the call taxonomy types they are. Fields without a clear type
# (staff hours, willingness to invest) are left out rather than guessed.
MAPPING: Final[dict[str, tuple[str, Any]]] = {
    "pain": ("need.primary_pain", lambda v: {"text": _short(v)}),
    "desired_outcome": ("need.goal", lambda v: {"text": _short(v)}),
    "purchase_risk": ("friction.blocker", lambda v: {"text": _short(v)}),
    "signing_authority": ("decision.maker", lambda v: {"name": _short(v)}),
    "net_budget_ceiling_inr": ("money.budget", _budget),
}


def answer(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """The authored facts in the engine's answer shape (what a model would return)."""
    items = []
    for fact in facts:
        mapped = MAPPING.get(str(fact.get("field")))
        evidence = fact.get("evidence") if isinstance(fact.get("evidence"), dict) else {}
        lines = evidence.get("line_ids") if isinstance(evidence.get("line_ids"), list) else []
        if mapped is None or not lines or fact.get("value") in (None, ""):
            continue
        type_key, shape = mapped
        items.append(
            {
                "type": type_key,
                "value": shape(fact["value"]),
                "segments": [str(line) for line in lines],
                "confidence": CONFIDENCE,
                "basis": "observed" if fact.get("label") == "Observed" else "inferred",
            }
        )
    return {"facts": items}


def _input(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def refusal(reason: str, **facts: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **facts}))


def _segments(transcript: object) -> tuple[list[extraction.Segment], str]:
    whole = transcript if isinstance(transcript, dict) else {}
    normalized = whole.get("normalized") if isinstance(whole.get("normalized"), dict) else {}
    revision = str(normalized.get("revision") or whole.get("revision") or "")
    return extraction.segments_from_transcript(normalized), revision


def _calls(session: Session, tenant_id: UUID) -> list[Any]:
    """The organisation's synthetic calls: key label, recording, submission, seller, transcript."""
    return list(
        session.execute(
            select(
                ConversationSubmissionLabelRevision.display_name,
                ConversationGuestSubmission.submission_id,
                ConversationGuestSubmission.recording_id,
                ConversationAcquisitionUsage.person_id,
                ConversationRecording.source_sha256,
                ConversationRecording.created_at,
                ConversationReportDraft.id,
                ConversationReportDraft.transcript,
            )
            .join(
                ConversationGuestSubmission,
                (
                    ConversationGuestSubmission.tenant_id
                    == ConversationSubmissionLabelRevision.tenant_id
                )
                & (
                    ConversationGuestSubmission.submission_id
                    == ConversationSubmissionLabelRevision.submission_id
                ),
            )
            .join(
                ConversationAcquisitionUsage,
                ConversationAcquisitionUsage.id == ConversationGuestSubmission.usage_id,
            )
            .join(
                ConversationRecording,
                ConversationRecording.id == ConversationGuestSubmission.recording_id,
            )
            .join(
                ConversationReportDraft,
                ConversationReportDraft.recording_id == ConversationGuestSubmission.recording_id,
            )
            .where(
                ConversationSubmissionLabelRevision.tenant_id == tenant_id,
                ConversationSubmissionLabelRevision.display_name.like(LABEL_PREFIX + "%"),
            )
            .order_by(ConversationSubmissionLabelRevision.display_name)
        ).all()
    )


def fill(
    session: Session, tenant_id: UUID, authored: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Each call's authored facts, validated and saved by the engine (synchronous part)."""
    principal = session.scalar(
        select(ConversationProcessingPrincipal.id).where(
            ConversationProcessingPrincipal.tenant_id == tenant_id
        )
    )
    calls: list[dict[str, Any]] = []
    made = 0
    for label, submission, recording, seller, source, created, draft, transcript in _calls(
        session, tenant_id
    ):
        entry: dict[str, Any] = {"call": label.removeprefix(LABEL_PREFIX)}
        calls.append(entry)
        if session.scalar(
            select(func.count()).select_from(CallObject).where(CallObject.recording_id == recording)
        ):
            entry["status"] = "has_call_data"
            continue
        segments, revision = _segments(transcript)
        drafts, dropped = extraction.validate_response(
            answer(authored.get(entry["call"]) or []), segments, types=taxonomy.FAST_TYPES
        )
        entry.update(facts=sorted(d.type_key for d in drafts), dropped=dropped)
        if not drafts:
            entry["status"] = "no_valid_facts"
            continue
        call = engine.Call(
            tenant_id=tenant_id,
            recording_id=recording,
            principal_id=principal or seller,
            checkpoint_id=draft,
            transcript_revision=revision,
            source_sha256=source,
            duration_ms=None,
            created_at=created,
            submission_id=submission,
            salesperson_id=seller,
            segments=segments,
        )
        connection = session.connection()
        common: dict[str, Any] = {
            "tenant_id": tenant_id,
            "recording_id": recording,
            "submission_id": submission,
            "person_id": call.person_id,
            "pipeline": "fast",
            "pipeline_version": engine.FAST_VERSION,
            "taxonomy_version": taxonomy.TAXONOMY_VERSION,
            "trigger": "operator",
            "transcript_revision": revision,
            "source_sha256": source,
            "provider": PROVIDER,
            "model_id": MODEL,
            "created_by": CREATED_BY,
            "created_at": now,
        }
        started, finished = uuid4(), uuid4()
        connection.execute(insert(CallDataRun).values(id=started, state="running", **common))
        connection.execute(
            insert(CallDataRun).values(
                id=finished,
                state="succeeded",
                cost_inr=Decimal("0"),
                duration_ms=0,
                counts={"facts": len(drafts), "dropped": dropped, "source": PROVIDER},
                supersedes_id=started,
                **common,
            )
        )
        entry["saved"] = engine.save_objects(
            connection,
            call,
            finished,
            drafts,
            policy.plan(drafts, lead=None, auto_filled={}, rejected=frozenset()),
            lead=None,
            pipeline="fast",
            pipeline_version=engine.FAST_VERSION,
            now=now,
        )
        entry["status"] = "filled"
        made += len(drafts)
    return {"calls": calls, "objects": made}


async def run(
    db: AsyncSession, spec: dict[str, Any], authored: dict[str, Any], *, apply: bool
) -> dict[str, Any]:
    """The change or its rehearsal, inside the caller's transaction."""
    command_id = UUID(spec["command_id"])
    tenant_id = UUID(spec["tenant_id"])
    tenant = await db.get(Tenant, tenant_id)
    if (
        tenant is None
        or tenant.name != spec["org_name"]
        or tenant.status != "active"
        or await db.get(ConversationSandboxOrganisation, tenant_id) is None
    ):
        raise refusal("not_the_named_active_sandbox", tenant_id=str(tenant_id))
    approver = await db.scalar(
        select(Person).where(func.lower(Person.email) == str(spec["approver_email"]).lower())
    )
    if approver is None:
        raise refusal("approver_not_found")
    now = datetime.now(UTC)
    report = await db.run_sync(lambda session: fill(session, tenant_id, authored, now))
    if report["objects"]:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, "audit")),
            reason="Owner approval: the directory reviewer's fictional calls with call facts",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "objects": report["objects"],
                "provider": PROVIDER,
                "cost_inr": "0",
                "calls": [c["call"] for c in report["calls"] if c.get("status") == "filled"],
            },
        )
    report["mode"] = "apply" if apply else "dry-run"
    report["status"] = "applied" if apply else "rehearsed_and_rolled_back"
    return report


async def main(spec_path: str, facts_path: str, apply: bool) -> int:
    settings = get_settings()
    engine_ = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine_, expire_on_commit=False)() as db:
            try:
                report = await run(db, _input(spec_path), _input(facts_path), apply=apply)
            except BaseException:
                await db.rollback()
                raise
            if apply:
                await db.commit()
            else:
                await db.rollback()
    finally:
        await engine_.dispose()
    print(json.dumps(report, default=str))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(asyncio.run(main(args[0], args[1], "--apply" in flags)))
