"""Organisation-wide Sales Xray activity: member totals and the calls behind them."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
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


def _activity_counts(totals: list[int]) -> dict[str, int | float]:
    calls, seconds, reports = totals
    return dict(calls=calls, recorded_minutes=round(seconds / 60, 1), reports_ready=reports)


async def organisation_activity(
    database: AsyncSession, actor: ActorContext, *, days: int, every_member: bool
) -> dict[str, Any]:
    """Read the selected organisation's calls in a fixed number of statements.

    ``every_member`` is the owner/admin view. Otherwise the scope is the actor's
    own row and calls, exactly as their saved-call library would list them.
    Aggregates cover all permitted calls since the inclusive rolling cutoff;
    dates are UTC and minutes use the call list's immutable duration receipt.
    Empty dates and reps with no permitted calls are omitted from aggregates.
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
        owner.label("owner"),
        Usage.created_at,
        Usage.reserved_seconds,
        has_report.label("has_report"),
        maintain_column_froms=True,
    ).subquery()
    # PostgreSQL timestamps carry offsets; bucket in UTC regardless of session timezone.
    timestamp = (
        func.timezone("UTC", reported.c.created_at)
        if database.get_bind().dialect.name == "postgresql"
        else reported.c.created_at
    )
    day = func.date(timestamp)
    per_day: dict[str, list[int]] = {}
    per_rep: dict[UUID, list[int]] = {}
    for person, date, calls, seconds, reports in await database.execute(
        select(
            reported.c.owner,
            day,
            func.count(),
            func.sum(reported.c.reserved_seconds),
            func.sum(case((reported.c.has_report, 1), else_=0)),
        ).group_by(reported.c.owner, day)
    ):
        for totals in (
            per_day.setdefault(str(date), [0, 0, 0]),
            per_rep.setdefault(person, [0, 0, 0]),
        ):
            for index, count in enumerate((calls, seconds, reports)):
                totals[index] += count
    names = {
        person.id: person.display_name or _mask_email(person.email)
        for person in await database.scalars(select(Person).where(Person.id.in_(per_rep)))
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
                reports_ready=per_rep.get(person_id, [0, 0, 0])[2],
                last_call_at=None
                if last_call is None
                else last_call.replace(tzinfo=UTC).isoformat(),
            )
        )
    return dict(
        members=members,
        per_day=[dict(date=date, **_activity_counts(per_day[date])) for date in sorted(per_day)],
        per_rep=[
            dict(
                person_id=str(person),
                name=names.get(person, "[redacted]"),
                **_activity_counts(totals),
            )
            for person, totals in sorted(per_rep.items(), key=lambda row: (-row[1][0], str(row[0])))
        ],
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
