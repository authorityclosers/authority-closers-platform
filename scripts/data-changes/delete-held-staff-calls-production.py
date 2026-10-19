"""Delete owner-approved held staff call copies on production (owner order, 19 Oct 2026).

Owner (Suyash Kulkarni, chat, 19 Oct): "approve delete: the 46 held staff-owned call copies in
held-staff-calls-delete-list.txt (Ankita 13, Swamini 33, production, uploaded 18 Oct 22:34-23:24 UTC,
never analysed), then import all 64 under my company account and analyse them."

Uses the app's own deletion (ConversationApplication._request_owned_deletion, the same port as
GuestOwnership.request_deletion and the staging organisation tool); the erasure worker then removes
the media. Dry run unless --apply. One transaction. Refuses any call that is not on the approved list,
not in the approved organisation, not owned by the two approved staff accounts, or that has a report.
One audit event per call. Prints ids and counts only.

Run inside the production API container:
    docker exec -i <api> python - <input.json> [--apply] < delete-held-staff-calls-production.py
input.json: {"tenant_id", "staff_person_ids", "approver_person_id", "command_id", "snapshot",
"submission_ids": [...]}
"""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor


async def main(path: str, apply: bool) -> int:
    spec = json.load(open(path))
    tenant = UUID(spec["tenant_id"])
    staff = {UUID(p) for p in spec["staff_person_ids"]}
    approver = UUID(spec["approver_person_id"])
    command = UUID(spec["command_id"])
    wanted = [UUID(s) for s in spec["submission_ids"]]
    engine = create_async_engine(get_settings().database_url)
    results: list[dict[str, object]] = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            app = ConversationApplication(db)
            for submission in wanted:
                link = await db.scalar(
                    select(ConversationGuestSubmission).where(
                        ConversationGuestSubmission.submission_id == submission,
                        ConversationGuestSubmission.tenant_id == tenant,
                    )
                )
                if link is None:
                    results.append({"submission": str(submission), "status": "refused_no_binding"})
                    continue
                owner = (
                    await db.execute(
                        text(
                            "select person_id from conversation_acquisition_usage"
                            " where id = :u and tenant_id = :t"
                        ),
                        {"u": link.usage_id, "t": tenant},
                    )
                ).scalar()
                if owner not in staff:
                    results.append({"submission": str(submission), "status": "refused_owner"})
                    continue
                query = select(ConversationRecording).where(
                    ConversationRecording.id == link.recording_id
                )
                if apply:
                    query = query.with_for_update().execution_options(populate_existing=True)
                recording = await db.scalar(query)
                if recording is None or recording.tenant_id != tenant:
                    results.append({"submission": str(submission), "status": "refused_recording"})
                    continue
                if recording.state in {"deleting", "deleted"}:
                    results.append({"submission": str(submission), "status": "already_deleted"})
                    continue
                reports = (
                    await db.execute(
                        text(
                            "select count(*) from conversation_report_drafts"
                            " where recording_id = :r and erased_at is null"
                        ),
                        {"r": recording.id},
                    )
                ).scalar()
                if reports:
                    results.append({"submission": str(submission), "status": "refused_has_report"})
                    continue
                row = {
                    "submission": str(submission),
                    "recording": str(recording.id),
                    "before": recording.state,
                    "status": "eligible",
                }
                if apply:
                    key = str(uuid5(command, f"delete:{recording.id}"))
                    await app._request_owned_deletion(
                        ProcessingActor(link.person_id, link.tenant_id, link.processing_lease_id),
                        recording,
                        key=key,
                        now=app.clock(),
                    )
                    await append_audit_event(
                        db,
                        tenant_id=tenant,
                        actor_person_id=approver,
                        actor_type="operator",
                        action="conversation.recording.owner_approved_deletion",
                        resource_type="conversation_recording",
                        resource_id=recording.id,
                        request_id=key,
                        reason="Owner approval 19 Oct 2026: held staff copies, never analysed, re-imported under the company account",
                        payload={"command_id": str(command), "snapshot": spec["snapshot"]},
                    )
                    row["status"] = "applied"
                results.append(row)
            refused = [r for r in results if str(r["status"]).startswith("refused")]
            if apply and refused:
                raise SystemExit(json.dumps({"refused": refused}))
    finally:
        await engine.dispose()
    counts: dict[str, int] = {}
    for r in results:
        counts[str(r["status"])] = counts.get(str(r["status"]), 0) + 1
    print(json.dumps({"mode": "apply" if apply else "dry-run", "counts": counts}))
    for r in results:
        if r["status"] not in {"eligible", "applied"}:
            print(json.dumps(r))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    raise SystemExit(asyncio.run(main(args[0], "--apply" in sys.argv[1:])))
