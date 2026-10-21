"""Move a Google sign-in (and its email) from a new, empty account onto an existing person.

Owner order, 21 Oct 2026 (Suyash Kulkarni, laptop orchestrator chat): "I need it to be that when she
login with authorityclosers@gmail.com with this" (the seller's existing profile) and "I fucking need
all data and all profile same as pervious one to bne on the authorityclosers@gmail.com".

A seller's work (leads, memberships, calls) lives on her existing person. She signed in with the
company Gmail, which created a second, empty person. In one transaction this:
  1. checks the source person is empty (no leads, no recordings, no membership beyond learner);
  2. clears the source person's email (it can no longer sign in) and ends its live sessions;
  3. sets the target person's email to the Gmail address, verified when Google verified it;
  4. moves the Gmail Google sign-in key from the source to the target person;
  5. writes one audit event per person, naming the approver.
Nothing is deleted. The target's other Google key stays linked but no longer matches its email.

Run inside the production API container with the deployed settings:
    docker exec -i <api> python - '<input JSON or path>' [--apply] < move-sign-in-email-production.py
input: {"command_id", "tenant_id", "approver_email", "email", "source_person_id",
"target_person_id", "identity_id", "issue"}. Dry run unless --apply. Rerunning after apply reports
"already_applied" and changes nothing. Prints masked emails and ids only.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event


def _mask(email: str | None) -> str | None:
    return None if email is None else re.sub(r"^(.{3}).*(@.*)$", r"\1***\2", email)


async def main(path: str, apply: bool) -> int:
    # The container's filesystem is read-only, so the input may also be passed inline as JSON.
    spec = json.loads(path) if path.lstrip().startswith("{") else json.load(open(path))
    command_id = UUID(spec["command_id"])
    tenant_id = UUID(spec["tenant_id"])
    email = spec["email"].strip().lower()
    source = UUID(spec["source_person_id"])
    target = UUID(spec["target_person_id"])
    identity = UUID(spec["identity_id"])
    engine = create_async_engine(get_settings().database_url)
    report: dict = {"mode": "apply" if apply else "dry-run", "email": _mask(email)}
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            q = lambda sql, **kw: db.execute(text(sql), kw)  # noqa: E731
            approver = (
                await q("select id from persons where lower(email) = :e", e=spec["approver_email"].lower())
            ).scalar_one()
            people = {
                row.id: row
                for row in (
                    await q(
                        "select id, email, email_verified_at, status, revision from persons"
                        " where id in (:s, :t) order by id for update",
                        s=source,
                        t=target,
                    )
                ).all()
            }
            if set(people) != {source, target}:
                raise SystemExit(json.dumps({"refused": "person_missing", **report}))
            key = (
                await q(
                    "select id, person_id, issuer, revision from provider_identities where id = :i for update",
                    i=identity,
                )
            ).one()
            src, tgt = people[source], people[target]
            report["before"] = {
                "source": {"id": str(source), "email": _mask(src.email), "status": src.status},
                "target": {"id": str(target), "email": _mask(tgt.email), "status": tgt.status},
                "google_key_person": str(key.person_id),
            }
            if (tgt.email or "").lower() == email and key.person_id == target and src.email is None:
                report["status"] = "already_applied"
                print(json.dumps(report))
                return 0
            if (src.email or "").lower() != email or key.person_id != source or src.email_verified_at is None:
                raise SystemExit(json.dumps({"refused": "source_not_as_expected", **report}))
            if tgt.status != "active" or key.issuer != "https://accounts.google.com":
                raise SystemExit(json.dumps({"refused": "target_or_key_not_as_expected", **report}))
            held = {
                "leads": "select count(*) from lead_desk_leads where owner_person_id = :p",
                "recordings": "select count(*) from conversation_recordings where person_id = :p",
                "non_learner_memberships": "select count(*) from memberships where person_id = :p and role <> 'learner'",
                "other_google_keys": "select count(*) from provider_identities where person_id = :p and id <> :i",
            }
            source_holds = {name: (await q(sql, p=source, i=identity)).scalar_one() for name, sql in held.items()}
            report["source_holds"] = source_holds
            if any(source_holds.values()):
                raise SystemExit(json.dumps({"refused": "source_not_empty", **report}))
            live = (
                await q(
                    "select count(*) from sessions where person_id = :p and revoked_at is null and expires_at > now()",
                    p=source,
                )
            ).scalar_one()
            target_leads = (
                await q("select count(*) from lead_desk_leads where owner_person_id = :p", p=target)
            ).scalar_one()
            report["plan"] = {
                "source_email": "cleared",
                "source_sessions_ended": live,
                "target_email": _mask(email),
                "google_key_moves_to": str(target),
                "target_keeps_leads": target_leads,
            }
            if not apply:
                report["status"] = "eligible"
                print(json.dumps(report))
                return 0
            now = datetime.now(UTC)
            await q(
                "update persons set email = null, revision = revision + 1, updated_at = :n where id = :p",
                n=now,
                p=source,
            )
            await q(
                "update sessions set revoked_at = :n, revocation_reason = 'sign_in_moved_owner_order',"
                " revision = revision + 1 where person_id = :p and revoked_at is null",
                n=now,
                p=source,
            )
            await q(
                "update persons set email = :e, email_verified_at = :v, revision = revision + 1,"
                " updated_at = :n where id = :p",
                e=email,
                v=src.email_verified_at,
                n=now,
                p=target,
            )
            await q(
                "update provider_identities set person_id = :t, revision = revision + 1 where id = :i",
                t=target,
                i=identity,
            )
            reason = "Owner order 21 Oct 2026: the company Gmail signs in to the seller's existing profile"
            for person, action in (
                (target, "identity.sign_in_email_moved_in"),
                (source, "identity.sign_in_email_moved_out"),
            ):
                await append_audit_event(
                    db,
                    tenant_id=tenant_id,
                    actor_person_id=approver,
                    actor_type="operator",
                    action=action,
                    resource_type="person",
                    resource_id=person,
                    request_id=str(uuid5(command_id, f"audit:{person}")),
                    reason=reason,
                    payload={
                        "email": _mask(email),
                        "source_person_id": str(source),
                        "target_person_id": str(target),
                        "provider_identity_id": str(identity),
                        "sessions_ended": live if person == source else 0,
                        "issue": spec.get("issue"),
                        "command_id": str(command_id),
                    },
                )
            report["status"] = "applied"
    finally:
        await engine.dispose()
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    raise SystemExit(asyncio.run(main(args[0], "--apply" in sys.argv[1:])))
