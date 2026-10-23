"""Feedback answers: write one, the person's own asking state, and the team's summary.

Answers are never changed. "How often may we ask" is worked out from them: the newest
answer per moment, answers in the last day and week, and the moments a person said not to
ask about again. Stores never commit: the request's transaction does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.feedback.models import FeedbackResponse
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Tenant

RATING = {1: "bad", 2: "okay", 3: "good"}


@dataclass(frozen=True, slots=True)
class NewFeedback:
    person_id: UUID
    tenant_id: UUID | None
    command_id: UUID
    moment: str
    subject: str | None
    kind: str
    rating: int | None
    comment: str | None
    route: str
    release: str | None
    context: dict[str, Any]


class FeedbackStore:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def find_command(self, person_id: UUID, command_id: UUID) -> FeedbackResponse | None:
        found: FeedbackResponse | None = await self.database.scalar(
            select(FeedbackResponse).where(
                FeedbackResponse.person_id == person_id,
                FeedbackResponse.command_id == command_id,
            )
        )
        return found

    async def add(self, answer: NewFeedback, *, now: datetime) -> FeedbackResponse:
        row = FeedbackResponse(
            id=uuid4(),
            person_id=answer.person_id,
            tenant_id=answer.tenant_id,
            command_id=answer.command_id,
            moment=answer.moment,
            subject=answer.subject,
            kind=answer.kind,
            rating=answer.rating,
            comment=answer.comment,
            route=answer.route,
            release=answer.release,
            context=answer.context,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        return row

    async def state(self, person_id: UUID, *, now: datetime) -> dict[str, Any]:
        """What the app needs to decide whether it may ask this person now."""
        mine = FeedbackResponse.person_id == person_id
        opted = (
            await self.database.scalars(
                select(FeedbackResponse.moment)
                .where(mine, FeedbackResponse.kind == "opt_out")
                .distinct()
            )
        ).all()
        last = (
            await self.database.execute(
                select(FeedbackResponse.moment, func.max(FeedbackResponse.created_at))
                .where(mine)
                .group_by(FeedbackResponse.moment)
            )
        ).all()
        day, week = (
            await self.database.execute(
                select(
                    func.count().filter(FeedbackResponse.created_at >= now - timedelta(days=1)),
                    func.count().filter(FeedbackResponse.created_at >= now - timedelta(days=7)),
                ).where(mine, FeedbackResponse.kind != "opt_out")
            )
        ).one()
        subjects = (
            await self.database.scalars(
                select(FeedbackResponse.subject)
                .where(mine, FeedbackResponse.subject.is_not(None))
                .order_by(FeedbackResponse.created_at.desc())
                .limit(50)
            )
        ).all()
        return {
            "opted_out": sorted(opted),
            "last": {moment: at.isoformat() for moment, at in last},
            "asked_today": int(day or 0),
            "asked_this_week": int(week or 0),
            "subjects": [subject for subject in subjects if subject],
        }

    async def summary(
        self, *, now: datetime, days: int, moment: str | None = None
    ) -> dict[str, Any]:
        """Trends for the team: by moment, by release, by day, and the newest comments."""
        since = now - timedelta(days=days)
        scope = [FeedbackResponse.created_at >= since]
        if moment is not None:
            scope.append(FeedbackResponse.moment == moment)

        def counts() -> list[Any]:
            rated = FeedbackResponse.kind == "rating"
            return [
                func.count().filter(rated, FeedbackResponse.rating == 3).label("good"),
                func.count().filter(rated, FeedbackResponse.rating == 2).label("okay"),
                func.count().filter(rated, FeedbackResponse.rating == 1).label("bad"),
                func.count().filter(FeedbackResponse.kind == "dismissed").label("dismissed"),
                func.count().filter(FeedbackResponse.kind == "opt_out").label("opted_out"),
                func.count().filter(FeedbackResponse.comment.is_not(None)).label("comments"),
            ]

        def shaped(row: Any) -> dict[str, int]:
            return {
                key: int(getattr(row, key) or 0)
                for key in ("good", "okay", "bad", "dismissed", "opted_out", "comments")
            }

        by_moment = (
            await self.database.execute(
                select(FeedbackResponse.moment, *counts())
                .where(*scope)
                .group_by(FeedbackResponse.moment)
                .order_by(FeedbackResponse.moment)
            )
        ).all()
        release = func.coalesce(FeedbackResponse.release, "unknown")
        by_release = (
            await self.database.execute(
                select(release.label("release"), func.max(FeedbackResponse.created_at), *counts())
                .where(*scope)
                .group_by(release)
                .order_by(func.max(FeedbackResponse.created_at).desc())
                .limit(12)
            )
        ).all()
        day = func.date_trunc("day", FeedbackResponse.created_at)
        by_day = (
            await self.database.execute(
                select(day.label("day"), *counts()).where(*scope).group_by(day).order_by(day)
            )
        ).all()
        recent = (
            await self.database.execute(
                select(FeedbackResponse, Tenant.name, Person.display_name, Person.email)
                .outerjoin(Tenant, Tenant.id == FeedbackResponse.tenant_id)
                .outerjoin(Person, Person.id == FeedbackResponse.person_id)
                .where(*scope, FeedbackResponse.kind == "rating")
                .order_by(
                    case((FeedbackResponse.comment.is_not(None), 0), else_=1),
                    FeedbackResponse.created_at.desc(),
                )
                .limit(60)
            )
        ).all()
        # Bad share this week against the week before, for the alert on the page.
        week = now - timedelta(days=7)
        fortnight = now - timedelta(days=14)
        rated = FeedbackResponse.kind == "rating"
        trend = (
            await self.database.execute(
                select(
                    func.count().filter(rated, FeedbackResponse.created_at >= week),
                    func.count().filter(
                        rated, FeedbackResponse.rating == 1, FeedbackResponse.created_at >= week
                    ),
                    func.count().filter(
                        rated,
                        FeedbackResponse.created_at >= fortnight,
                        FeedbackResponse.created_at < week,
                    ),
                    func.count().filter(
                        rated,
                        FeedbackResponse.rating == 1,
                        FeedbackResponse.created_at >= fortnight,
                        FeedbackResponse.created_at < week,
                    ),
                ).where(*([FeedbackResponse.moment == moment] if moment else []))
            )
        ).one()
        return {
            "days": days,
            "moments": [{"moment": row[0], **shaped(row)} for row in by_moment],
            "releases": [
                {"release": row[0], "last_at": row[1].isoformat(), **shaped(row)}
                for row in by_release
            ],
            "by_day": [{"day": row[0].date().isoformat(), **shaped(row)} for row in by_day],
            "recent": [
                {
                    "feedback_id": str(answer.id),
                    "created_at": answer.created_at.isoformat(),
                    "moment": answer.moment,
                    "rating": RATING.get(answer.rating or 0),
                    "comment": answer.comment,
                    "route": answer.route,
                    "release": answer.release,
                    "organisation": organisation,
                    "person": name or email,
                }
                for answer, organisation, name, email in recent
            ],
            "week": {
                "rated": int(trend[0] or 0),
                "bad": int(trend[1] or 0),
                "rated_before": int(trend[2] or 0),
                "bad_before": int(trend[3] or 0),
            },
        }
