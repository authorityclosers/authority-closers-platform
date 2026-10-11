"""One member's Sales Xray activity over recent weeks, for the people pages."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

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
from ac_platform.organisations.activity import _activity_counts, _mask_email

MAX_CALLS = 50
WEEK = timedelta(days=7)


async def person_activity(
    database: AsyncSession,
    actor: ActorContext,
    *,
    person_id: UUID,
    weeks: int,
    every_member: bool,
) -> dict[str, Any] | None:
    """One person's calls in the selected organisation, week by week.

    The scope is the organisation activity read's: owners and admins
    (``every_member``) read anyone's calls; a member reads only their own and
    gets ``None`` for anyone else. Weeks are rolling 7-day windows ending now,
    oldest first, so every count covers the same calls the totals do (not only
    the newest ``MAX_CALLS`` that are listed).
    """
    assert actor.tenant_id is not None
    if not every_member and person_id != actor.person_id:
        return None
    now = datetime.now(UTC)
    since = now - weeks * WEEK
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
        Usage.created_at >= since, owner == person_id
    )
    rows = (
        await database.execute(
            scope.with_only_columns(
                Usage.submission_id,
                Usage.created_at,
                Usage.reserved_seconds,
                Recording.state,
                has_report,
                plan_state,
                label,
                maintain_column_froms=True,
            ).order_by(Usage.created_at.desc(), Usage.submission_id.desc())
        )
    ).all()
    buckets = [[0, 0, 0] for _ in range(weeks)]
    totals = [0, 0, 0]
    for _id, created_at, seconds, _state, ready, _plan, _label in rows:
        at = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
        index = weeks - 1 - int((now - at) / WEEK)
        for counts in (totals, buckets[min(max(index, 0), weeks - 1)]):
            counts[0] += 1
            counts[1] += seconds
            counts[2] += 1 if ready else 0
    person = await database.get(Person, person_id)
    name = "[redacted]" if person is None else person.display_name or _mask_email(person.email)
    return dict(
        person_id=str(person_id),
        weeks=[
            dict(
                start=(now - (weeks - index) * WEEK).isoformat(),
                **_activity_counts(counts),
            )
            for index, counts in enumerate(buckets)
        ],
        totals=_activity_counts(totals),
        calls=[
            dict(
                id=str(submission_id),
                owner_person_id=str(person_id),
                owner_name=name,
                label=display_name,
                created_at=created_at.replace(tzinfo=UTC).isoformat(),
                duration_seconds=seconds,
                state="report_ready" if ready else plan or recording_state,
                has_report=ready,
            )
            for (
                submission_id,
                created_at,
                seconds,
                recording_state,
                ready,
                plan,
                display_name,
            ) in rows[:MAX_CALLS]
        ],
    )
