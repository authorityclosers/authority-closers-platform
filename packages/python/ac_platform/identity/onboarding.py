"""Authenticated progressive onboarding for the bounded learner profile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import OnboardingStatus, Person, PersonStatus


class OnboardingError(Exception):
    """Base class for expected learner onboarding failures."""


class OnboardingNotFound(OnboardingError):
    """The authenticated person is unavailable."""


class OnboardingConcurrencyError(OnboardingError):
    """A stale browser attempted to replace newer onboarding state."""


class OnboardingValidationError(OnboardingError):
    """The bounded onboarding snapshot does not satisfy its contract."""


@dataclass(frozen=True, slots=True)
class OnboardingSnapshot:
    person_id: UUID
    experience_context: str | None
    learning_goal: str | None
    practice_situation: str | None
    weekly_minutes: int | None
    status: str
    current_step: int
    revision: int
    updated_at: datetime

    @property
    def next_action_href(self) -> str:
        return "/"

    @property
    def next_action_reason(self) -> str:
        if self.status == OnboardingStatus.NOT_STARTED.value:
            return "Complete or skip the profile to continue to the published catalog."
        return (
            "Open the server-published catalog. No unreviewed personalized "
            "course mapping has been inferred from these answers."
        )


def _optional_text(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise OnboardingValidationError(f"{field} exceeds {maximum} characters")
    return normalized


def _snapshot(person: Person) -> OnboardingSnapshot:
    return OnboardingSnapshot(
        person_id=person.id,
        experience_context=person.experience_context,
        learning_goal=person.learning_goal,
        practice_situation=person.practice_situation,
        weekly_minutes=person.weekly_minutes,
        status=person.onboarding_status,
        current_step=person.onboarding_step,
        revision=person.onboarding_revision,
        updated_at=person.updated_at,
    )


class LearnerOnboardingService:
    """Read and replace only the authenticated person's onboarding snapshot."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, person_id: UUID, *, lock: bool = False) -> OnboardingSnapshot:
        statement = select(Person).where(
            Person.id == person_id,
            Person.status == PersonStatus.ACTIVE.value,
        )
        if lock:
            statement = statement.with_for_update()
        person = await self.session.scalar(statement)
        if person is None:
            raise OnboardingNotFound("the learner profile is unavailable")
        return _snapshot(person)

    async def save(
        self,
        person_id: UUID,
        *,
        expected_revision: int,
        experience_context: str | None,
        learning_goal: str | None,
        practice_situation: str | None,
        weekly_minutes: int | None,
        status: str,
        current_step: int,
        now: datetime | None = None,
    ) -> OnboardingSnapshot:
        person = await self.session.scalar(
            select(Person)
            .where(
                Person.id == person_id,
                Person.status == PersonStatus.ACTIVE.value,
            )
            .with_for_update()
        )
        if person is None:
            raise OnboardingNotFound("the learner profile is unavailable")
        if person.onboarding_revision != expected_revision:
            raise OnboardingConcurrencyError("the learner profile changed; refresh and retry")
        try:
            normalized_status = OnboardingStatus(status)
        except ValueError as error:
            raise OnboardingValidationError("onboarding status is not supported") from error
        if normalized_status is OnboardingStatus.NOT_STARTED:
            raise OnboardingValidationError("a saved onboarding state cannot be not_started")
        if not 1 <= current_step <= 3:
            raise OnboardingValidationError("current_step must be between 1 and 3")
        if weekly_minutes is not None and not 15 <= weekly_minutes <= 1200:
            raise OnboardingValidationError("weekly_minutes must be between 15 and 1200")

        context = _optional_text(
            experience_context,
            field="experience_context",
            maximum=64,
        )
        goal = _optional_text(learning_goal, field="learning_goal", maximum=240)
        situation = _optional_text(
            practice_situation,
            field="practice_situation",
            maximum=500,
        )
        if normalized_status is OnboardingStatus.COMPLETED and (context is None or goal is None):
            raise OnboardingValidationError(
                "completed onboarding requires experience_context and learning_goal"
            )

        person.experience_context = context
        person.learning_goal = goal
        person.practice_situation = situation
        person.weekly_minutes = weekly_minutes
        person.onboarding_status = normalized_status.value
        person.onboarding_step = current_step
        person.onboarding_revision += 1
        person.revision += 1
        person.updated_at = (now or datetime.now(UTC)).astimezone(UTC)
        await self.session.flush()
        return _snapshot(person)


__all__ = [
    "LearnerOnboardingService",
    "OnboardingConcurrencyError",
    "OnboardingError",
    "OnboardingNotFound",
    "OnboardingSnapshot",
    "OnboardingValidationError",
]
