"""Organisation-wide Sales Xray activity: member totals and the calls behind them."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_library import (
    _account_library_query,
    _report_columns,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationVisitorClaim as Claim,
)
from ac_platform.conversation_intelligence.models import ConversationRecording as Recording
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision as Label,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.organisations.usage import member_usage
from ac_platform.tenancy.models import Membership

MAX_CALLS = 500


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "[redacted]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


async def organisation_activity(
    database: AsyncSession, actor: ActorContext, *, days: int, every_member: bool
) -> dict[str, Any]:
    """Read the selected organisation's calls in a fixed number of statements.

    ``every_member`` is the owner/admin view. Otherwise the scope is the actor's
    own row and calls, exactly as their saved-call library would list them.
    """
    assert actor.tenant_id is not None
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    owner = func.coalesce(Usage.person_id, Claim.person_id)
    has_report, plan_state = _report_columns()
    label = (
        select(Label.display_name)
        .where(Label.tenant_id == Usage.tenant_id, Label.submission_id == Usage.submission_id)
        .order_by(Label.revision.desc())
        .limit(1)
        .correlate(Usage)
        .scalar_subquery()
    )
    scope = _account_library_query(actor, now, every_owner=every_member).where(
        Usage.created_at >= since
    )
    call_rows = (
        await database.execute(
            scope.with_only_columns(
                Usage.submission_id,
                owner,
                Usage.created_at,
                Usage.reserved_seconds,
                Recording.state,
                has_report,
                plan_state,
                label,
                maintain_column_froms=True,
            )
            .order_by(Usage.created_at.desc(), Usage.submission_id.desc())
            .limit(MAX_CALLS)
        )
    ).all()
    reported = scope.with_only_columns(
        owner.label("owner"), has_report.label("has_report"), maintain_column_froms=True
    ).subquery()
    reports_ready = {
        person: count
        for person, count in await database.execute(
            select(reported.c.owner, func.count())
            .where(reported.c.has_report)
            .group_by(reported.c.owner)
        )
    }
    names = {
        person.id: person.display_name or _mask_email(person.email)
        for person in await database.scalars(
            select(Person).where(Person.id.in_({row[1] for row in call_rows}))
        )
    }
    usage = await member_usage(database, actor.tenant_id, since)
    statement = (
        select(Person.id)
        .join(Membership, Membership.person_id == Person.id)
        .where(
            Membership.tenant_id == actor.tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
            # The tenant's processing principal holds a membership; it is not a person.
            Membership.role.in_(("owner", "admin", "member")),
        )
        .order_by(Person.email, Person.id)
    )
    if not every_member:
        statement = statement.where(Person.id == actor.person_id)
    members = []
    for person_id in await database.scalars(statement):
        seconds, calls, last_call = usage.get(person_id, (0, 0, None))
        members.append(
            dict(
                person_id=str(person_id),
                calls=calls,
                minutes=round(seconds / 60, 1),
                reports_ready=reports_ready.get(person_id, 0),
                last_call_at=None
                if last_call is None
                else last_call.replace(tzinfo=UTC).isoformat(),
            )
        )
    return dict(
        members=members,
        calls=[
            dict(
                id=str(submission_id),
                owner_person_id=str(owner_id),
                owner_name=names.get(owner_id, "[redacted]"),
                label=display_name,
                created_at=created_at.replace(tzinfo=UTC).isoformat(),
                duration_seconds=seconds,
                state="report_ready" if ready else plan or recording_state,
                has_report=ready,
            )
            for (
                submission_id,
                owner_id,
                created_at,
                seconds,
                recording_state,
                ready,
                plan,
                display_name,
            ) in call_rows
        ],
    )
