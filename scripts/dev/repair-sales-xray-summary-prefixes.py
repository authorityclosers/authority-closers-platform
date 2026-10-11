#!/usr/bin/env python3
"""Prepare the reviewed synthetic summary wording; supersede exact dev drafts only.

Default: offline, source-pinned plan. --preview-live reads the exact dev database.
--apply requires that preview's plan digest and a separately recorded approval.
Old drafts, source bundles, quotes and person-recorded outcomes are preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.models import (
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reports import parse_report_draft
from ac_platform.conversation_intelligence.synthetic_import_contracts import SyntheticCallBundle
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSyntheticRecord,
)

spec = importlib.util.spec_from_file_location(
    "dev_sandbox_loader", Path(__file__).with_name("load-sales-xray-sandbox.py")
)
if spec is None or spec.loader is None:
    raise RuntimeError("The reviewed dev loader is unavailable.")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

POLICY = "synthetic-summary-prefix-removal/1"
SOURCE_SHA256 = "26adb0da3ca993a04167ffbfc967348687c025b1d594f8dea9c251834474adec"
PREFIXES = ("The conversation ended as Won: ", "The conversation ended as Lost: ")
EXPECTED_COUNTS = {"reports": 3360, "Won": 391, "Lost": 436, "other_sentences": 12493}
Payload = dict[str, Any]
Candidate = tuple[SyntheticCallBundle, Payload, Payload, Payload, Payload, str]


def revised_summary(bundle: SyntheticCallBundle) -> tuple[list[str], list[Payload]]:
    """Remove only reviewed whole-sentence prefixes; verify their literal buyer fact."""
    original = bundle.report["the_big_picture"]["executive_summary"]
    position = bundle.report["where_the_deal_stands"]["prospects_position"]
    revised, changes = list(original), []
    for index, sentence in enumerate(original):
        for label, prefix in zip(("Won", "Lost"), PREFIXES, strict=True):
            if sentence.startswith(prefix):
                suffix = sentence[len(prefix) :]
                if not position or suffix != position + ".":
                    raise ValueError(
                        "A summary suffix must equal the complete authored buyer fact."
                    )
                revised[index] = suffix
                changes.append({"sentence_index": index, "prefix_label": label})
    return revised, changes


def candidate(
    bundle: SyntheticCallBundle,
) -> tuple[Payload, Payload, Payload, Payload, str, list[Payload]]:
    summary, changes = revised_summary(bundle)
    before, transcript, proof, source = loader.adapted_report(bundle)
    after = deepcopy(before)
    if changes:
        original = " ".join(bundle.report["the_big_picture"]["executive_summary"])
        # The reviewed corpus fits in full; refuse truncation or an adapter change.
        if len(original) > 600 or before["summary"] != "Synthetic test call. " + original:
            raise ValueError("The original summary no longer matches the reviewed adapter.")
        after["summary"] = "Synthetic test call. " + " ".join(summary)
        if "pillars" not in before or before["pillars"]["summary"] != original:
            raise ValueError("The complete reviewed pillar summary is required.")
        after["pillars"]["summary"] = " ".join(summary)
        checked = parse_report_draft(
            after,
            transcript["normalized"],
            source_label=after["source_label"],
            canonical_read=True,
        ).model_dump(mode="json")
        if checked != after:
            raise ValueError("Canonical validation changed more than the two summary fields.")
    return before, after, transcript, proof, source, changes


def plan(root: Path) -> tuple[Payload, list[Candidate]]:
    counts: Counter[str] = Counter()
    source_hashes, entries, candidates = [], [], []
    for bundle in loader.bundles(root):
        source_hashes.append(content_hash(bundle.model_dump(mode="json", by_alias=True)))
        _, changes = revised_summary(bundle)
        counts["reports"] += 1
        counts["other_sentences"] += len(
            bundle.report["the_big_picture"]["executive_summary"]
        ) - len(changes)
        if not changes:
            continue
        for change in changes:
            counts[change["prefix_label"]] += 1
        before, after, transcript, proof, source, _ = candidate(bundle)
        key = bundle.metadata["call_id"]
        entries.append(
            {
                "call_key": key,
                "previous_report_id": str(loader.identifier("report", key)),
                "replacement_report_id": str(loader.identifier(POLICY, key)),
                "previous_report_sha256": content_hash(before),
                "replacement_report_sha256": content_hash(after),
                "source_sha256": source,
                "changes": changes,
            }
        )
        candidates.append((bundle, before, after, transcript, proof, source))
    digest = content_hash(source_hashes)
    if digest != SOURCE_SHA256 or dict(counts) != EXPECTED_COUNTS or len(entries) != 827:
        raise ValueError("The publication does not match the reviewed source and exact counts.")
    proposal = {
        "policy": POLICY,
        "tenant_id": str(loader.TARGET),
        "environment": "development",
        "source_sha256": digest,
        "counts": dict(counts),
        "reports": entries,
    }
    return {**proposal, "plan_sha256": content_hash(proposal)}, candidates


async def supersede(
    db: AsyncSession,
    proposal: Payload,
    candidates: list[Candidate],
    *,
    approver: UUID,
    approval: str,
    apply: bool,
    expected_plan_sha256: str | None = None,
) -> Payload:
    """Caller owns one transaction: all new drafts and their audit, or none."""
    proposal_body = {k: v for k, v in proposal.items() if k != "plan_sha256"}
    if proposal["plan_sha256"] != content_hash(proposal_body):
        raise ValueError("The plan digest is inconsistent.")
    if (
        proposal["policy"] != POLICY
        or proposal["tenant_id"] != str(loader.TARGET)
        or proposal["environment"] != "development"
        or proposal["source_sha256"] != SOURCE_SHA256
        or proposal["counts"] != EXPECTED_COUNTS
    ):
        raise ValueError("The plan must name the reviewed policy, dev tenant and source.")
    if apply and expected_plan_sha256 != proposal["plan_sha256"]:
        raise ValueError("Apply requires the exact previously reviewed plan digest.")
    if not 1 <= len(approval.strip()) <= 160:
        raise ValueError("Use a separately recorded bounded approval reference.")
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(loader.TARGET.bytes[:8], signed=True)},
    )
    await loader.target(db, approver)
    now, run_id = datetime.now(UTC), uuid4()
    counts = {"reports_superseded": 0, "reports_already_superseded": 0}
    for entry, (bundle, before, after, transcript, proof, digest) in zip(
        proposal["reports"], candidates, strict=True
    ):
        key = bundle.metadata["call_id"]
        old_id, new_id = loader.identifier("report", key), loader.identifier(POLICY, key)
        if (
            entry["call_key"] != key
            or entry["previous_report_id"] != str(old_id)
            or entry["replacement_report_id"] != str(new_id)
            or entry["previous_report_sha256"] != content_hash(before)
            or entry["replacement_report_sha256"] != content_hash(after)
            or entry["source_sha256"] != digest
        ):
            raise ValueError("The candidate does not match its pinned plan entry.")
        recording = await db.scalar(
            select(ConversationRecording)
            .where(ConversationRecording.id == loader.identifier("recording", key))
            .with_for_update()
        )
        old = await db.get(ConversationReportDraft, old_id)
        preserved = await db.get(ConversationSyntheticRecord, (loader.TARGET, "call", key, 1))
        run = await db.get(ConversationRun, loader.identifier("run", key))
        if (
            recording is None
            or old is None
            or run is None
            or preserved is None
            or recording.state != "ready"
            or recording.deleted_at is not None
            or recording.generation != 1
            or run.state != "completed"
            or run.recipe_revision != loader.POLICY
            or run.recording_id != recording.id
            or run.tenant_id != loader.TARGET
            or run.person_id != recording.person_id
            or old.run_id != run.id
            or old.payload != before
            or old.transcript != transcript
            or old.evidence_receipt != proof
            or old.source_sha256 != digest
            or preserved.payload != bundle.model_dump(mode="json", by_alias=True)
            or preserved.payload_sha256 != content_hash(preserved.payload)
        ):
            raise ValueError("The exact intact original synthetic call and report are required.")
        ConversationReports._validated(old, recording)
        later_run = await db.scalar(
            select(ConversationRun.id).where(
                ConversationRun.recording_id == recording.id, ConversationRun.id != run.id
            )
        )
        latest = await db.scalar(
            select(ConversationReportDraft)
            .where(ConversationReportDraft.recording_id == recording.id)
            .order_by(ConversationReportDraft.created_at.desc(), ConversationReportDraft.id.desc())
            .limit(1)
        )
        replacement = await db.get(ConversationReportDraft, new_id)
        if later_run is not None or latest is None or latest.id not in {old_id, new_id}:
            raise ValueError("A later run or report needs separate review; refuse supersession.")
        if replacement is not None:
            ConversationReports._validated(replacement, recording)
            if (
                latest.id != new_id
                or replacement.run_id != old.run_id
                or replacement.payload != after
                or replacement.transcript != old.transcript
                or replacement.evidence_receipt != old.evidence_receipt
            ):
                raise ValueError("The existing replacement does not match this exact repair.")
            counts["reports_already_superseded"] += 1
            continue
        if now <= old.created_at:
            raise ValueError("A replacement must be later than the preserved original.")
        replacement = ConversationReportDraft(
            id=new_id,
            tenant_id=old.tenant_id,
            person_id=old.person_id,
            recording_id=old.recording_id,
            run_id=old.run_id,
            source_revision=old.source_revision,
            source_sha256=old.source_sha256,
            report_sha256=content_hash(after),
            transcript_sha256=old.transcript_sha256,
            profile_sha256=old.profile_sha256,
            evidence_receipt_sha256=old.evidence_receipt_sha256,
            payload=after,
            transcript=deepcopy(old.transcript),
            evidence_receipt=deepcopy(old.evidence_receipt),
            created_at=now,
        )
        ConversationReports._validated(replacement, recording)
        if apply:
            db.add(replacement)
        counts["reports_superseded"] += 1
    result = {
        "run_id": str(run_id),
        "tenant_id": str(loader.TARGET),
        "environment": "development",
        "issue": "AUT-1676",
        "policy": POLICY,
        "plan_sha256": proposal["plan_sha256"],
        "source_sha256": proposal["source_sha256"],
        "approver_person_id": str(approver),
        "approval_reference": approval,
        "applied": apply,
        "provider_calls": 0,
        "charged_seconds": 0,
        **counts,
    }
    if apply and counts["reports_superseded"]:
        await db.flush()
        await AuditRepository(db).append(
            tenant_id=loader.TARGET,
            actor_person_id=approver,
            actor_type="operator",
            action="conversation.synthetic_dev_summary_superseded",
            resource_type="conversation_synthetic_import",
            resource_id=run_id,
            payload={**result, "reports": proposal["reports"]},
            reason=approval,
            now=now,
        )
    return result


async def execute(args: argparse.Namespace) -> Payload:
    proposal, candidates = plan(args.dataset)
    if not args.preview_live and not args.apply:
        return {**proposal, "applied": False, "live_checked": False, "provider_calls": 0}
    url = loader.dev_database_url(os.environ.get("AC_DATABASE_URL", ""))
    engine = create_async_engine(url, hide_parameters=True, echo=False)
    try:
        async with AsyncSession(engine) as db, db.begin():
            result = await supersede(
                db,
                proposal,
                candidates,
                approver=args.approver_person_id,
                approval=args.approval_reference,
                apply=args.apply,
                expected_plan_sha256=args.expected_plan_sha256,
            )
        return {**result, "live_checked": True}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview-live", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--approver-person-id", type=UUID)
    parser.add_argument("--approval-reference")
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if (args.preview_live or args.apply) and (
        args.approver_person_id is None or not args.approval_reference
    ):
        parser.error(
            "Live preview/apply requires the current owner and recorded approval reference."
        )
    if args.apply and not args.expected_plan_sha256:
        parser.error("Apply requires the exact plan digest from the live preview.")
    try:
        result = asyncio.run(execute(args))
    except Exception:
        parser.exit(
            2, "Summary repair refused; no transaction applied. Content/details withheld.\n"
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
