from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import OnboardingStatus, Person, PersonStatus
from ac_platform.identity.onboarding import (
    LearnerOnboardingService,
    OnboardingConcurrencyError,
    OnboardingValidationError,
)

NOW = datetime(2026, 8, 31, 10, tzinfo=UTC)


def _person() -> Person:
    return Person(
        id=uuid4(),
        email="learner@example.com",
        status=PersonStatus.ACTIVE.value,
        onboarding_status=OnboardingStatus.NOT_STARTED.value,
        onboarding_step=1,
        onboarding_revision=0,
        revision=2,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_onboarding_save_is_self_scoped_revisioned_and_explainable() -> None:
    person = _person()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = person
    service = LearnerOnboardingService(session)

    saved = await service.save(
        person.id,
        expected_revision=0,
        experience_context=" sales ",
        learning_goal=" Ask a clearer next-step question ",
        practice_situation="",
        weekly_minutes=30,
        status=OnboardingStatus.COMPLETED.value,
        current_step=3,
        now=NOW,
    )

    assert saved.experience_context == "sales"
    assert saved.learning_goal == "Ask a clearer next-step question"
    assert saved.practice_situation is None
    assert saved.status == OnboardingStatus.COMPLETED.value
    assert saved.revision == 1
    assert saved.next_action_href == "/"
    assert "No unreviewed personalized course mapping" in saved.next_action_reason
    assert person.revision == 3
    session.flush.assert_awaited_once()


async def test_onboarding_rejects_stale_writes_before_mutation() -> None:
    person = _person()
    person.onboarding_revision = 4
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = person

    with pytest.raises(OnboardingConcurrencyError, match="changed"):
        await LearnerOnboardingService(session).save(
            person.id,
            expected_revision=3,
            experience_context="sales",
            learning_goal="A goal",
            practice_situation=None,
            weekly_minutes=None,
            status=OnboardingStatus.IN_PROGRESS.value,
            current_step=2,
        )

    session.flush.assert_not_awaited()


async def test_completed_onboarding_requires_context_and_goal() -> None:
    person = _person()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = person

    with pytest.raises(OnboardingValidationError, match="requires"):
        await LearnerOnboardingService(session).save(
            person.id,
            expected_revision=0,
            experience_context=None,
            learning_goal=None,
            practice_situation=None,
            weekly_minutes=None,
            status=OnboardingStatus.COMPLETED.value,
            current_step=3,
        )
