#!/usr/bin/env python3
"""Owner-approved data change: load authored synthetic calls into the AC Sandbox
organisation of a hosted environment (development, staging or production).

Derived from scripts/dev/load-sales-xray-sandbox.py (AUT-1676) with these bounded
differences: the target organisation, environment and database host are explicit
arguments; the tenant row is locked FOR SHARE (not FOR UPDATE) so ordinary API
requests are never blocked while the transaction runs; `--per-business N` loads a
deterministic subset (the first N calls of each fictional seller in journey order)
so production stays inside the logical backup bound; history summaries are
optional and bounded. Dry-run by default. One transaction, idempotent replay,
refuses changed content, writes one audit event naming the approver.

Runtime-injected AC_DATABASE_URL must name the environment's ac_platform database
and AC_ENVIRONMENT must match --environment. No provider transport, schema change,
login credential or paid job.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.dipak_report import normalize_pillars
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.org_insights import OrganisationInsights
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reports import load_report_profile, parse_report_draft
from ac_platform.conversation_intelligence.speaker_map import (
    project_speaker_roles,
    resolve_speaker_map,
)
from ac_platform.conversation_intelligence.speaker_map_models import ConversationSpeakerMapRevision
from ac_platform.conversation_intelligence.speaker_map_store import normalize_speaker_decisions
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.conversation_intelligence.synthetic_import_contracts import SyntheticCallBundle
from ac_platform.conversation_intelligence.synthetic_import_dataset import (
    bundles,
    date,
    exact_file,
    lines,
    read_json,
    summaries,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Organisation, Tenant

TARGET = UUID("90ec1979-0d85-4829-ba8d-cabde2a9a9d3")  # replaced by --target-tenant at runtime
ENVIRONMENT = "development"  # replaced by --environment at runtime
ENVIRONMENTS = ("development", "staging", "production")
NAMESPACE = UUID("1dfdfac9-bfa2-49ab-b061-d98776454e0f")
POLICY = "synthetic-dev-authored/1"
EXPECTED_BUNDLES = 3360
STOCK_SKILL_NOTE = "Relevant behaviour is evidenced by the cited turn."
STOCK_MOMENT_REASONS = {
    "This changed the information available for the buying decision.",
    "The concern needed a specific answer; raising it alone did not establish approval or a loss.",
}


def short_title(value: Any, limit: int = 48) -> str:
    """Keep complete authored words, with room for the truncation marker."""
    value = " ".join(value.split()) if isinstance(value, str) else ""
    if len(value) <= limit:
        return value
    prefix = value[: limit - 1]
    if not value[limit - 1].isspace():
        prefix = prefix.rsplit(" ", 1)[0] if " " in prefix else ""
    return prefix.rstrip(" ,;:–-") + "…"


def sentence(value: str) -> str:
    value = value.strip()
    if not value or value.rstrip("\"'”’»").endswith((".", "!", "?", "।", "…")):
        return value
    return value + "."


def identifier(kind: str, key: str) -> UUID:
    return uuid5(NAMESPACE, f"{TARGET}:{kind}:{key}")


def hosted_database_url(raw: str, *, environment: str, expected_host: str) -> str:
    url = make_url(raw)
    declared = os.environ.get("AC_ENVIRONMENT", "")
    if declared == "dev":
        declared = "development"
    if (
        environment not in ENVIRONMENTS
        or url.get_backend_name() != "postgresql"
        or not expected_host
        or url.host != expected_host
        or url.port not in {None, 5432}
        or url.database != "ac_platform"
        or url.query
        or declared != environment
    ):
        raise ValueError("Select the exact environment and its ac_platform database host.")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def subset(root: Path, per_business: int) -> frozenset[str] | None:
    """The first `per_business` calls of every fictional seller, in journey and call order."""
    if per_business <= 0:
        return None
    rows = list(csv.DictReader(exact_file(root, "MANIFEST.csv").open(encoding="utf-8")))
    if len(rows) != EXPECTED_BUNDLES:
        raise ValueError("The publication manifest must enumerate all 3,360 full calls.")
    chosen: set[str] = set()
    for business in sorted({row["business_id"] for row in rows}):
        ordered = sorted(
            (row for row in rows if row["business_id"] == business),
            key=lambda row: (row["journey_id"], int(row["sequence"]), row["call_id"]),
        )
        chosen.update(row["call_id"] for row in ordered[:per_business])
    return frozenset(chosen)


def representatives(root: Path) -> list[dict[str, Any]]:
    people = list(lines(exact_file(root, "simulation/operations/people.jsonl.gz")))
    result = [
        p
        for p in people
        if p["person_id"].rsplit("-", 1)[-1] in {"R1", "R2", "R3", "R4", "R5", "R6"}
    ]
    if len(result) != 60 or len({p["person_id"] for p in result}) != 60:
        raise ValueError("The publication must contain exactly 60 initial representatives.")
    for person in result:
        if person.get("synthetic") is not True or person.get("synthetic_identity") is not True:
            raise ValueError("Only explicitly synthetic people may become sandbox members.")
        if not person["fields"]["email"].endswith("@example.invalid"):
            raise ValueError("Synthetic members must use the reserved invalid email domain.")
    return result


def authored_speaker_decisions(bundle: SyntheticCallBundle, transcript: dict) -> list[dict]:
    """Copy declared fictional participants, never identify a real voice."""
    known = {row["speaker_id"] for row in transcript["segments"]}
    participants = {}
    for row in bundle.transcript["participants"]:
        label = row.get("speaker")
        if label not in known:
            continue
        role = {"rep": "salesperson", "prospect": "prospect", "other": "other"}.get(label)
        expected = (
            bundle.metadata.get("rep_id")
            if label == "rep"
            else bundle.metadata.get("prospect_id")
            if label == "prospect"
            else row.get("person_id")
        )
        if (
            not role
            or not isinstance(expected, str)
            or not expected
            or row.get("synthetic") is not True
            or row.get("person_id") != expected
            or label in participants
            or any(
                line.get("person_id") != expected
                for line in bundle.transcript["lines"]
                if line.get("speaker") == label
            )
        ):
            raise ValueError("Synthetic speaker roles must match the declared source participants.")
        participants[label] = {
            "speaker_id": label,
            "role": role,
            "display_name": row.get("name"),
        }
    return normalize_speaker_decisions(list(participants.values()), transcript)


async def preserve_speaker_map(
    db: AsyncSession,
    *,
    bundle: SyntheticCallBundle,
    transcript: dict,
    approver: UUID,
    now: datetime,
    apply: bool,
    counts: Counter,
) -> None:
    submission = identifier("submission", bundle.metadata["call_id"])
    existing = await db.scalar(
        select(ConversationSpeakerMapRevision)
        .where(
            ConversationSpeakerMapRevision.tenant_id == TARGET,
            ConversationSpeakerMapRevision.submission_id == submission,
        )
        .limit(1)
    )
    if existing is not None:
        counts["speaker_maps_preserved"] += 1
        return
    decisions = authored_speaker_decisions(bundle, transcript)
    counts["speaker_maps_created"] += 1
    if apply:
        db.add(
            ConversationSpeakerMapRevision(
                id=identifier("speaker-map", bundle.metadata["call_id"]),
                tenant_id=TARGET,
                submission_id=submission,
                revision=1,
                transcript_revision=transcript["revision"],
                speakers=decisions,
                actor_person_id=approver,
                created_at=now,
            )
        )


def authored_pillars(
    bundle: SyntheticCallBundle, transcript: dict, evidence: Callable[[Any], list[dict]]
) -> dict | None:
    """Copy authored report parts; omit unsupported claims rather than complete them."""
    report = bundle.report
    picture = report["the_big_picture"]
    worked = report["what_worked_and_what_didnt"]
    deal = report["where_the_deal_stands"]
    if (
        not isinstance(report["how_the_call_played_out"], dict)
        or not isinstance(report["moments_that_mattered"], list)
        or not isinstance(deal, dict)
    ):
        return None

    def text(value: Any, limit: int = 150) -> str:
        return value.strip()[:limit].rstrip() if isinstance(value, str) else ""

    def refs(value: Any) -> list[dict]:
        return evidence(value)[:2]

    def highlight(value: Any, *, positive: bool) -> dict | None:
        if not isinstance(value, dict) or not (cited := refs(value.get("evidence"))):
            return None
        label = value.get("action" if positive else "what_it_affected")
        short = short_title(" ".join(label.split()[:8]) if isinstance(label, str) else "")
        observation = (
            " ".join(
                part
                for part in (
                    sentence(text(value.get("action"))),
                    sentence(text(value.get("why_it_helped"))),
                )
                if part
            )
            if positive
            else text(value.get("what_happened"))
        )
        return (
            {"text": short_title(observation, 150), "short": short, "evidence": cited}
            if short
            else None
        )

    def findings(rows: list, *, positive: bool) -> list[dict]:
        result = []
        for row in rows:
            if not isinstance(row, dict) or not (cited := refs(row.get("evidence"))):
                continue
            what = text(row.get("action" if positive else "what_happened"))
            effect = text(row.get("why_it_helped" if positive else "what_it_affected"))
            if what and effect:
                result.append(
                    {
                        "title": short_title(what),
                        "what": what,
                        "evidence": cited,
                        **(
                            {"why_it_helped": effect}
                            if positive
                            else {"what_it_affected": effect, "possible_areas": []}
                        ),
                    }
                )
        return result[:3]

    try:
        speaker_map = resolve_speaker_map(
            transcript,
            account_holder_name=None,
            user_revision={
                "revision": 1,
                "transcript_revision": transcript["revision"],
                "speakers": authored_speaker_decisions(bundle, transcript),
            },
        )
        timeline = []
        for phase in report["how_the_call_played_out"].get("timeline", []):
            if not isinstance(phase, dict):
                continue
            cited = refs({"line_ids": [phase.get("line_id")]})
            start = cited[0]["start_ms"]
            if (
                text(phase.get("phase"), 48)
                and phase.get("start_ms") == start
                and start < transcript["duration_ms"]
                and (not timeline or start > timeline[-1]["start_ms"])
            ):
                timeline.append(
                    {"label": text(phase["phase"], 48), "start_ms": start, "evidence": cited[:1]}
                )
        moments = []
        kinds = {
            "Strong Moment",
            "Turning Point",
            "Buying Signal",
            "Important Miss",
            "Objection",
            "Price Moment",
            "Decision Moment",
            "Trust Moment",
            "Commitment",
            "Risk",
        }
        for row in report["moments_that_mattered"]:
            if not isinstance(row, dict) or row.get("category") not in kinds:
                continue
            # The publication usually has no opening/response explanation for a miss.
            # Its authored concern is still shown under What Didn't.
            moved = text(row.get("moved_toward")) or None
            missed = text(row.get("what_was_missed")) or None
            if row["category"] == "Important Miss" and (not moved or not missed):
                continue
            cited = refs(row.get("evidence"))
            title, why = short_title(row.get("title")), text(row.get("why_it_mattered"))
            if not why:
                continue
            if why in STOCK_MOMENT_REASONS:
                if row["category"] == "Important Miss":
                    # A stock reason does not explain this specific missed chance.
                    continue
                why = ""
            if cited and title:
                moments.append(
                    {
                        "kind": row["category"],
                        "title": title,
                        "evidence": cited,
                        "why": why,
                        "moved_toward": moved,
                        "what_was_missed": missed,
                        "price_stated": None,
                        "prospect_response": None,
                    }
                )
        moments = moments[:5]

        next_event = None
        event = deal.get("next_event")
        if isinstance(event, dict) and event.get("agreed") is True and event.get("at"):
            at = datetime.fromisoformat(event["at"])
            # Only an exact spoken form of the authored date may be a replay label.
            suffix = (
                "th"
                if 10 <= at.day % 100 <= 20
                else {1: "st", 2: "nd", 3: "rd"}.get(at.day % 10, "th")
            )
            dates = [
                at.strftime("%d %B %Y at %I:%M %p, India time"),
                f"{at.day}{suffix} {at.strftime('%B')} at "
                f"{at.hour % 12 or 12}:{at.minute:02d} {at.strftime('%p').lower()}",
            ]
            if at.utcoffset() != timedelta(hours=5, minutes=30):
                dates = []
            for line in bundle.transcript["lines"]:
                if "next_step" not in line.get("annotations", []):
                    continue
                when = next((d for d in dates if d in line["text"] and len(d) <= 60), None)
                if when and text(event.get("type")):
                    next_event = {
                        "text": text(event["type"]),
                        "when": when,
                        "evidence": refs({"line_ids": [line["line_id"]]}),
                    }
                    break

        outcome = None
        status = picture.get("call_outcome")
        if status in {
            "Follow-up Set",
            "Decision Pending",
            "Deferred",
            "Meeting Booked",
            "Disqualified",
            "No Clear Next Step",
            "Still Open",
        }:
            # The authored closing markers bind the report's status to its ending.
            ending = next(
                (
                    line
                    for line in reversed(bundle.transcript["lines"])
                    if {"terminal", "commitment", "soft_end"}.intersection(
                        line.get("annotations", [])
                    )
                ),
                None,
            )
            if ending and text(deal.get("prospects_position")):
                outcome = {
                    "status": status,
                    "line": text(deal["prospects_position"]),
                    "evidence": refs({"line_ids": [ending["line_id"]]}),
                }

        quality = deal.get("commitment_quality")
        deal_part = None
        if quality == "Unclear" or (quality in {"Clear", "Soft"} and next_event):
            deal_part = {
                "position": None,
                "blocker": None,
                "prospect_commitments": [],
                "seller_commitments": [],
                "next_event": next_event,
                "commitment_quality": quality,
                "still_unclear": [
                    text(q, 120)
                    for q in deal.get("what_still_needs_to_become_clear", [])
                    if text(q, 120)
                ][:4],
                "deal_action": text(deal.get("recommended_deal_action")) or None,
                "coaching_mission": None,
            }
        candidate = {
            "version": "report-pillars/1",
            "outcome": outcome,
            "summary": text(" ".join(picture["executive_summary"]), 600),
            "biggest_influence": None,
            "strongest_part": highlight(picture.get("strongest_part"), positive=True),
            "biggest_concern": highlight(picture.get("biggest_concern"), positive=False),
            "next_step": next_event if picture.get("next_agreed_step") == event else None,
            "timeline": timeline[:8],
            "key_change": None,
            "worked": findings(worked["what_worked"], positive=True),
            "didnt": findings(worked["what_didnt"], positive=False),
            "moments": moments,
            "deeper": None,
            "deal": deal_part,
            "most_important_moment": next(
                (i for i, m in enumerate(moments) if m["kind"] == "Turning Point"),
                0 if moments else None,
            ),
        }
        return normalize_pillars(
            candidate,
            transcript=transcript,
            speaker_roles=project_speaker_roles(speaker_map),
            normalize_evidence=lambda ref: ref,
            canonical_read=True,
            canonical_synthetic=transcript.get("synthetic") is True,
        ).model_dump(mode="json")
    except (ValueError, KeyError, TypeError):
        # Optional presentation never prevents the accepted canonical call import.
        return None


def adapted_report(bundle: SyntheticCallBundle) -> tuple[dict, dict, dict, str]:
    """Translate authored citations, never evaluate speech or answer-key fixture truth."""
    native = canonical(bundle.transcript).decode()
    revision = hashlib.sha256(native.encode()).hexdigest()
    source_hash = revision
    segments = [
        {
            "id": row["line_id"],
            "speaker_id": row["speaker"],
            "start_ms": row["start_ms"],
            "end_ms": row["end_ms"],
            "text": row["text"],
        }
        for row in bundle.transcript["lines"]
    ]
    transcript = {
        "source_sha256": source_hash,
        "revision": revision,
        "timebase_id": "decoded_audio_track",
        "duration_ms": bundle.metadata["duration_ms"],
        "segments": segments,
        "synthetic": True,
        "timing_source": bundle.transcript["timing_source"],
    }
    by_id = {row["id"]: row for row in segments}

    def evidence(value: Any) -> list[dict]:
        if not isinstance(value, dict):
            return []
        result = []
        for line_id in value.get("line_ids", [])[:8]:
            segment = by_id.get(line_id)
            if segment is None:
                raise ValueError("An authored citation references a missing transcript line.")
            # A multi-line source citation is split into its exact published lines.
            quote = value.get("quote", "")
            if not quote or quote not in segment["text"]:
                quote = segment["text"]
            result.append(
                {
                    "segment_id": line_id,
                    "quote": quote[:1000],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                }
            )
        return result

    report = bundle.report
    picture = report["the_big_picture"]
    worked = report["what_worked_and_what_didnt"]

    def finding(row: dict, *, positive: bool) -> dict | None:
        refs = evidence(row.get("evidence"))
        if not refs:
            return None
        title = row["action"] if positive else row["what_happened"]
        explanation = row["why_it_helped"] if positive else row["what_it_affected"]
        return {"title": title[:240], "explanation": explanation[:4000], "evidence": refs}

    strengths = [
        f
        for row in worked["what_worked"]
        if isinstance(row, dict) and (f := finding(row, positive=True))
    ][:3]
    missed = [
        f
        for row in worked["what_didnt"]
        if isinstance(row, dict) and (f := finding(row, positive=False))
    ][:10]
    focus = bundle.coaching["current_focus"]
    focus_refs = []
    for moment in bundle.coaching["diagnosis"].get("playable_moments", []):
        focus_refs.extend(evidence(moment))
    improvements = (
        [
            {
                "title": focus["label"][:240],
                "explanation": bundle.coaching["teaching"]["text_lesson"]["quick_idea"][:4000],
                "evidence": focus_refs[:8],
            }
        ]
        if focus_refs
        else []
    )
    profile = load_report_profile()
    skills = {row["skill_id"]: row for row in report["your_skills_on_this_call"]}
    dimensions = []
    for number, expected in enumerate(profile["dimensions"], 1):
        row = skills[f"skill-{number}"]
        if row["name"] != expected["label"]:
            raise ValueError("The authored skill does not match the controlled report profile.")
        refs = evidence(row.get("evidence"))
        observation = row.get("observation") or "No transcript citation was published."
        if isinstance(observation, str) and observation.strip() == STOCK_SKILL_NOTE:
            observation = "" if refs else "No transcript citation was published."
        dimensions.append(
            {
                "dimension_id": expected["id"],
                "label": expected["label"],
                "status": "observed" if refs else "insufficient_evidence",
                "observation": observation,
                "citations": expected["citations"],
                "evidence": refs,
            }
        )
        if refs and row.get("state") in {"Observed", "Needs Attention", "Strongly Demonstrated"}:
            dimensions[-1]["call_state"] = {
                "Observed": "observed",
                "Needs Attention": "needs_attention",
                "Strongly Demonstrated": "strongly_demonstrated",
            }[row["state"]]
    payload = parse_report_draft(
        {
            "summary": "Synthetic test call. " + " ".join(picture["executive_summary"]),
            "strengths": strengths,
            "missed_opportunities": missed,
            "improvements": improvements,
            "objection_analysis": [],
            "closing_analysis": [],
            "verdict": picture["call_outcome"] + ": " + picture["biggest_influence"],
            "review_status": "draft_not_dipak_adjudicated",
            "dimensions": dimensions,
        },
        transcript,
        source_label="Synthetic · " + bundle.metadata["call_id"],
        canonical_read=True,
    ).model_dump(mode="json")
    pillars = authored_pillars(bundle, transcript, evidence)
    if pillars is not None:
        try:
            enriched = parse_report_draft(
                {**payload, "pillars": pillars},
                transcript,
                source_label=payload["source_label"],
                canonical_read=True,
            )
            if enriched.pillars is not None:
                payload = enriched.model_dump(mode="json")
        except ValueError:
            pass
    receipt = {
        "schema_id": "ac.sales-xray.private-proof-reference/1",
        "approval_receipt_sha256": content_hash({"issue": "AUT-1676", "order": "AUT-1701"}),
        "transcription_response_sha256": revision,
        "generation_receipt_sha256": content_hash(bundle.report),
        "source_review_receipt_sha256": content_hash(bundle.coaching),
        "new_provider_calls": 0,
    }
    return payload, {"native_json": native, "normalized": transcript}, receipt, source_hash


async def preserved(
    db: AsyncSession,
    *,
    kind: str,
    key: str,
    business: str,
    at: datetime,
    payload: dict,
    approver: UUID,
    now: datetime,
) -> bool:
    identity = (TARGET, kind, key, 1)
    digest = content_hash(payload)
    existing = await db.get(ConversationSyntheticRecord, identity)
    if existing is not None:
        if (
            existing.payload_sha256 != digest
            or existing.business_id != business
            or existing.occurred_at != at
        ):
            raise ValueError("A preserved synthetic revision changed; supersede it explicitly.")
        return False
    db.add(
        ConversationSyntheticRecord(
            tenant_id=TARGET,
            kind=kind,
            synthetic_key=key,
            revision=1,
            business_id=business,
            imported_by_person_id=approver,
            payload_sha256=digest,
            payload=payload,
            occurred_at=at,
            imported_at=now,
        )
    )
    return True


async def target(db: AsyncSession, approver: UUID) -> None:
    # FOR SHARE: enough to fence tenant lifecycle changes without blocking API reads.
    tenant = await db.scalar(select(Tenant).where(Tenant.id == TARGET).with_for_update(read=True))
    member = await db.get(Membership, (TARGET, approver))
    if (
        tenant is None
        or tenant.name != "AC Sandbox"
        or tenant.status != "active"
        or await db.get(Organisation, TARGET) is None
        or member is None
        or member.role != "owner"
        or member.status != "active"
        or member.ended_at is not None
    ):
        raise ValueError(
            "The exact active AC Sandbox and its current approving owner are required."
        )


async def load(
    db: AsyncSession,
    *,
    root: Path,
    approver: UUID,
    approval: str,
    apply: bool,
    include_history: bool = False,
    per_business: int = 0,
    history_max_rows: int = 0,
) -> dict:
    """Caller owns one transaction. Dry-run reads and validates without adding rows."""
    await target(db, approver)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(TARGET.bytes[:8], signed=True)},
    )
    now = datetime.now(UTC)
    run_id = uuid4()
    reps = representatives(root)
    config = read_json(root, "simulation/config.json")
    if config.get("synthetic") is not True or not isinstance(config.get("start"), str):
        raise ValueError("The publication needs its explicit synthetic date baseline.")
    worlds = {}
    for business in sorted({p["person_id"].rsplit("-", 1)[0] for p in reps}):
        world = read_json(root, "world/" + business + ".json", maximum=8 * 1024 * 1024)
        if (
            world.get("synthetic") is not True
            or world.get("fictional") is not True
            or world.get("business_id") != business
        ):
            raise ValueError("World records must name their exact fictional selling business.")
        worlds[business] = world
    counts: Counter = Counter(
        {
            "members_created": 0,
            "calls_created": 0,
            "calls_skipped": 0,
            "reports_with_pillars": 0,
            "reports_without_pillars": 0,
            "speaker_maps_created": 0,
            "speaker_maps_preserved": 0,
            "summaries_created": 0,
            "summaries_skipped": 0,
            "summaries_validated": 0,
            "calls_excluded": 0,
        }
    )
    selected = subset(root, per_business)
    before = await db.scalar(
        select(func.count())
        .select_from(ConversationAcquisitionUsage)
        .where(
            ConversationAcquisitionUsage.tenant_id == TARGET,
            ConversationAcquisitionUsage.policy_revision == POLICY,
        )
    )
    if apply:
        if await db.get(ConversationSandboxOrganisation, TARGET) is None:
            db.add(
                ConversationSandboxOrganisation(
                    tenant_id=TARGET,
                    approved_by_person_id=approver,
                    approval_reference=approval,
                    created_at=now,
                )
            )
        for rep in reps:
            person_id = identifier("person", rep["person_id"])
            person = await db.get(Person, person_id)
            fields = rep["fields"]
            if person is None:
                db.add(
                    Person(
                        id=person_id,
                        email=fields["email"],
                        display_name=fields["name"],
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await db.flush()
                db.add(
                    Membership(
                        tenant_id=TARGET,
                        person_id=person_id,
                        role="member",
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
                counts["members_created"] += 1
            elif person.email != fields["email"] or person.display_name != fields["name"]:
                raise ValueError("A synthetic identity conflicts with an existing person.")
            else:
                membership = await db.get(Membership, (TARGET, person_id))
                if (
                    person.status != "active"
                    or membership is None
                    or membership.status != "active"
                    or membership.role != "member"
                    or membership.ended_at is not None
                ):
                    raise ValueError("An existing synthetic membership changed; do not restore it.")
            await preserved(
                db,
                kind="people",
                key=rep["person_id"],
                business=rep["person_id"].rsplit("-", 1)[0],
                at=date(rep, "fields.joined_on"),
                payload=rep,
                approver=approver,
                now=now,
            )
        for business, world in worlds.items():
            created = await preserved(
                db,
                kind="world",
                key=business,
                business=business,
                at=date(world, None, baseline=config["start"]),
                payload=world,
                approver=approver,
                now=now,
            )
            counts["worlds_created" if created else "worlds_skipped"] += 1
        await db.flush()
    principal = await db.scalar(
        select(ConversationProcessingPrincipal).where(
            ConversationProcessingPrincipal.tenant_id == TARGET
        )
    )
    if principal is None:
        processing_id = identifier("processing-person", "sandbox")
        principal = ConversationProcessingPrincipal(
            id=identifier("principal", "sandbox"),
            tenant_id=TARGET,
            person_id=processing_id,
            operator_reference="AUT-1676 dev loader",
            created_at=now,
        )
        if apply:
            db.add(Person(id=processing_id, display_name="Sandbox processing", status="active"))
            await db.flush()
            db.add(
                Membership(
                    tenant_id=TARGET, person_id=processing_id, role="processing", status="active"
                )
            )
            await db.flush()
            db.add(principal)
            await db.flush()
    elif principal.revoked_at is not None:
        raise ValueError("The sandbox processing principal was revoked.")
    rep_keys = {rep["person_id"] for rep in reps}
    source_hashes = []
    for bundle in bundles(root):
        key = bundle.metadata["call_id"]
        if bundle.metadata["rep_id"] not in rep_keys:
            raise ValueError("Every call must belong to an exact published initial representative.")
        payload, transcript, receipt, digest = adapted_report(bundle)
        source_hashes.append(content_hash(bundle.model_dump(mode="json", by_alias=True)))
        if selected is not None and key not in selected:
            counts["calls_excluded"] += 1
            continue
        counts["reports_with_pillars" if "pillars" in payload else "reports_without_pillars"] += 1
        binding = dict(tenant_id=TARGET, person_id=principal.person_id)
        recording_id, run, submission = (
            identifier(kind, key) for kind in ("recording", "run", "submission")
        )
        recording = ConversationRecording(
            id=recording_id,
            **binding,
            permission_id=identifier("permission", key),
            request_key="syn:" + str(submission),
            intent_sha256=digest,
            source_sha256=digest,
            source_bytes=len(canonical(bundle.transcript)),
            content_type="application/json",
            source_revision=1,
            generation=1,
            state="ready",
            created_at=bundle.occurred_at,
        )
        draft = ConversationReportDraft(
            id=identifier("report", key),
            **binding,
            recording_id=recording_id,
            run_id=run,
            source_revision=1,
            source_sha256=digest,
            report_sha256=content_hash(payload),
            transcript_sha256=content_hash(transcript),
            profile_sha256=content_hash(load_report_profile()),
            evidence_receipt_sha256=content_hash(receipt),
            payload=payload,
            transcript=transcript,
            evidence_receipt=receipt,
            created_at=bundle.occurred_at,
        )
        # Use the same canonical validation that the actual API read performs.
        ConversationReports._validated(draft, recording)
        existing = await db.get(ConversationReportDraft, draft.id)
        if existing is not None:
            if existing.report_sha256 != draft.report_sha256 or existing.source_sha256 != digest:
                raise ValueError("An already loaded call changed; do not overwrite its history.")
            source = await db.get(ConversationSyntheticRecord, (TARGET, "call", key, 1))
            if source is None or source.payload_sha256 != source_hashes[-1]:
                raise ValueError("The original authored bundle changed; supersede it explicitly.")
            await preserve_speaker_map(
                db,
                bundle=bundle,
                transcript=transcript["normalized"],
                approver=approver,
                now=now,
                apply=apply,
                counts=counts,
            )
            counts["calls_skipped"] += 1
            continue
        counts["calls_created"] += 1
        if not apply:
            await preserve_speaker_map(
                db,
                bundle=bundle,
                transcript=transcript["normalized"],
                approver=approver,
                now=now,
                apply=False,
                counts=counts,
            )
            continue
        owner_id = identifier("person", bundle.metadata["rep_id"])
        usage_id, lease_id, job_id = (identifier(kind, key) for kind in ("usage", "lease", "job"))
        at = bundle.occurred_at
        db.add(
            ConversationPermission(
                id=recording.permission_id,
                **binding,
                source_sha256=digest,
                provider="local",
                permission_reference=approval,
                retention_reference=f"AUT-1676 synthetic sandbox ({ENVIRONMENT})",
                created_at=at,
                expires_at=at + timedelta(minutes=1),
                retention_until=now + timedelta(days=365),
            )
        )
        db.add(
            Job(
                id=job_id,
                tenant_id=TARGET,
                kind="conversation.synthetic_dev_loaded",
                dedupe_key="synthetic-dev:" + str(submission),
                payload={"synthetic": True},
                status="succeeded",
                external_side_effect=False,
                created_at=at,
                available_at=at,
            )
        )
        db.add(
            ConversationAcquisitionUsage(
                id=usage_id,
                tenant_id=TARGET,
                person_id=owner_id,
                submission_id=submission,
                source_sha256=digest,
                duration_evidence_sha256=content_hash(bundle.metadata),
                reserved_seconds=max(1, (bundle.metadata["duration_ms"] + 999) // 1000),
                policy_revision=POLICY,
                created_at=at,
            )
        )
        await db.flush()
        db.add(recording)
        db.add(
            ConversationProcessingLease(
                id=lease_id,
                principal_id=principal.id,
                **binding,
                usage_id=usage_id,
                created_at=at,
                expires_at=at + timedelta(minutes=1),
            )
        )
        await db.flush()
        db.add(
            ConversationGuestSubmission(
                **binding,
                submission_id=submission,
                recording_id=recording_id,
                processing_lease_id=lease_id,
                usage_id=usage_id,
                source_sha256=digest,
                created_at=at,
            )
        )
        db.add(
            ConversationRun(
                id=run,
                **binding,
                recording_id=recording_id,
                request_key="syn:" + str(submission),
                intent_sha256=digest,
                recipe_revision=POLICY,
                generation=1,
                state="completed",
                job_id=job_id,
                created_at=at,
                completed_at=at,
            )
        )
        db.add(
            ConversationAcquisitionSettlement(
                usage_id=usage_id,
                charged_seconds=0,
                kind="no_work_performed",
                receipt_sha256=content_hash(receipt),
                created_at=now,
            )
        )
        db.add(
            ConversationReportMinuteEvent(
                usage_id=usage_id,
                revision=1,
                key=POLICY,
                kind="released",
                seconds=0,
                receipt_sha256=content_hash(receipt),
                created_at=now,
            )
        )
        await db.flush()
        await preserve_speaker_map(
            db,
            bundle=bundle,
            transcript=transcript["normalized"],
            approver=approver,
            now=now,
            apply=True,
            counts=counts,
        )
        db.add(draft)
        db.add(
            ConversationSubmissionLabelRevision(
                id=identifier("label", key),
                tenant_id=TARGET,
                submission_id=submission,
                revision=1,
                actor_person_id=approver,
                display_name=("Synthetic · " + key)[:120],
                created_at=at,
            )
        )
        await preserved(
            db,
            kind="call",
            key=key,
            business=bundle.metadata["business_id"],
            at=at,
            payload=bundle.model_dump(mode="json", by_alias=True),
            approver=approver,
            now=now,
        )
        await db.flush()
    if len(source_hashes) != EXPECTED_BUNDLES:
        raise ValueError("The sealed publication must contain all 3,360 full bundles.")
    if include_history:
        for index, row in enumerate(summaries(root)):
            if history_max_rows and index >= history_max_rows:
                break
            if apply:
                created = await preserved(
                    db,
                    kind=row.kind,
                    key=row.key,
                    business=row.business_id,
                    at=row.occurred_at,
                    payload=row.payload,
                    approver=approver,
                    now=now,
                )
                counts["summaries_created" if created else "summaries_skipped"] += 1
                if sum(counts[k] for k in ("summaries_created", "summaries_skipped")) % 500 == 0:
                    await db.flush()
            else:
                counts["summaries_validated"] += 1
    if apply:
        await db.flush()
        # Reuse the company's controlled synthetic adapter, including its
        # outcome vocabulary and deduplication of summaries/full bundles.
        insights = OrganisationInsights(db, TARGET)
        for _ in range(32):
            refreshed = await insights.refresh(now=now)
            counts["insight_rows_refreshed"] += refreshed["projected"]
            if refreshed["pending"] == 0:
                break
            if refreshed["projected"] == 0:
                raise ValueError("The normal Insights projection cannot advance.")
        else:
            raise ValueError("The normal Insights refresh exceeded its bounded load budget.")
    result = {
        "run_id": str(run_id),
        "tenant_id": str(TARGET),
        "environment": ENVIRONMENT,
        "issue": "AUT-1676",
        "per_business": per_business,
        "history_max_rows": history_max_rows,
        "approval_reference": approval,
        "approver_person_id": str(approver),
        "applied": apply,
        "source_sha256": content_hash(source_hashes),
        "members_validated": len(reps),
        "businesses_validated": len(worlds),
        "before_calls": before,
        "after_calls": before + counts["calls_created"] if apply else before,
        "provider_calls": 0,
        "charged_seconds": 0,
        **counts,
    }
    if apply:
        await db.flush()
        await AuditRepository(db).append(
            tenant_id=TARGET,
            actor_person_id=approver,
            actor_type="operator",
            action="conversation.synthetic_dev_loaded",
            resource_type="conversation_synthetic_import",
            resource_id=run_id,
            payload=result,
            reason=approval,
            now=now,
        )
    return result


async def execute(args: argparse.Namespace) -> dict:
    global TARGET, ENVIRONMENT
    TARGET = args.target_tenant
    ENVIRONMENT = args.environment
    url = hosted_database_url(
        os.environ.get("AC_DATABASE_URL", ""),
        environment=args.environment,
        expected_host=args.expect_db_host,
    )
    model_metadata()
    engine = create_async_engine(url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            return await load(
                db,
                root=args.dataset.resolve(),
                approver=args.approver_person_id,
                approval=args.approval_reference,
                apply=args.apply,
                include_history=args.include_history,
                per_business=args.per_business,
                history_max_rows=args.history_max_rows,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--approver-person-id", type=UUID, required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--include-history", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument(
        "--target-tenant", type=UUID, required=True, help="AC Sandbox organisation id"
    )
    parser.add_argument("--expect-db-host", required=True, help="environment PostgreSQL host")
    parser.add_argument("--per-business", type=int, default=0, help="0 = all calls per seller")
    parser.add_argument("--history-max-rows", type=int, default=0, help="0 = all summaries")
    args = parser.parse_args()
    if args.per_business < 0 or args.history_max_rows < 0:
        parser.error("Bounds must be non-negative.")
    if not 1 <= len(args.approval_reference) <= 160:
        parser.error("Use a bounded recorded owner approval reference.")
    try:
        result = asyncio.run(execute(args))
    except Exception:
        parser.exit(2, "Synthetic sandbox load failed; connection details and content withheld.\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
