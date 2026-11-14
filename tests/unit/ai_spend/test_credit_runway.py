"""AI credit runway (owner, 13 Nov 2026): an email before the prepaid Gemini credit ends."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from ac_platform.ai_spend import credit_email, credit_runway
from ac_platform.ai_spend.credit_runway import TopUp, runway
from ac_platform.conversation_intelligence.cost_metrics import Export, Step
from ac_platform.outbox.repository import DuplicateIntentError
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.providers.resend_email import render_email

TOPUP_AT = datetime(2026, 11, 13, 14, 24, tzinfo=UTC)
TOPUPS = (TopUp("gemini", "0146E3-722EE0-47B3D5", 2_000, TOPUP_AT),)


def step(at: datetime, rupees: float, provider: str = "gemini") -> Step:
    return Step(
        environment="production",
        call=None,
        company=None,
        stage="C4",
        provider=provider,
        model="gemini-3.8-flash",
        status="succeeded",
        attempts=1,
        input_tokens=0,
        output_tokens=0,
        audio_ms=0,
        elapsed_ms=None,
        paise=round(rupees * 100),
        at=at,
    )


def export(*steps: Step) -> Export:
    return Export(
        environment="production",
        generated_at=None,
        migration=None,
        window_days=120,
        steps=list(steps),
    )


def test_spend_since_the_top_up_and_the_week_s_burn_give_the_days_left() -> None:
    now = TOPUP_AT + timedelta(days=4)
    # Rs 300 a day for the last 7 days; only the 4 days since the top-up count as spent.
    steps = [step(now - timedelta(days=day, hours=1), 300) for day in range(7)]
    current = runway([export(*steps, step(now, 50, "openai"))], now, TOPUPS)
    assert current is not None
    assert (current.topup_inr, current.spent_inr) == (2_000, 1_200)
    assert (current.balance_inr, current.burn_inr_per_day) == (800, 300)
    assert current.days_left == 2 and current.alert
    # 17 Nov India time: 14 days to the month's end at Rs 300 = Rs 4,200, less Rs 800.
    assert (current.days_to_month_end, current.month) == (14, "November")
    assert current.add_inr == 3_500


def test_quiet_while_a_week_or_more_is_left_and_above_rs_300() -> None:
    now = TOPUP_AT + timedelta(days=1)
    current = runway([export(step(now - timedelta(hours=2), 70))], now, TOPUPS)
    assert current is not None
    assert current.burn_inr_per_day == 10 and current.days_left == 193
    assert not current.alert


def test_under_rs_300_alerts_even_with_nothing_spent_this_week() -> None:
    now = TOPUP_AT + timedelta(days=20)
    current = runway([export(step(TOPUP_AT + timedelta(days=2), 1_750))], now, TOPUPS)
    assert current is not None
    assert current.balance_inr == 250 and current.days_left is None
    assert current.alert
    # Nothing to cover this month: the Rs 2,000 floor.
    assert current.add_inr == credit_runway.FLOOR_INR


def test_no_top_up_yet_means_no_runway() -> None:
    assert runway([export()], TOPUP_AT - timedelta(days=1), TOPUPS) is None


def test_the_last_top_up_counts() -> None:
    later = TopUp("gemini", "0146E3-722EE0-47B3D5", 3_000, TOPUP_AT + timedelta(days=2))
    now = TOPUP_AT + timedelta(days=3)
    current = runway([export(step(TOPUP_AT + timedelta(days=1), 900))], now, (*TOPUPS, later))
    assert current is not None
    assert (current.topup_inr, current.spent_inr, current.balance_inr) == (3_000, 0, 3_000)


def test_the_seeded_top_ups_are_the_owner_s() -> None:
    assert [(item.amount_inr, item.at.date().isoformat()) for item in credit_runway.TOPUPS] == [
        (1_000, "2026-10-20"),
        (2_000, "2026-11-13"),
    ]
    assert {item.account for item in credit_runway.TOPUPS} == {"0146E3-722EE0-47B3D5"}


def _values() -> dict[str, Any]:
    now = TOPUP_AT + timedelta(days=4)
    steps = [step(now - timedelta(days=day, hours=1), 300) for day in range(7)]
    current = runway([export(*steps)], now, TOPUPS)
    assert current is not None
    return current.values(now.date())


def test_the_values_fit_the_email_s_outbox_route() -> None:
    values = _values()
    assert credit_email.ROUTE.normalize_payload(values) == values
    assert credit_email.checked(values) == values
    with pytest.raises(PermanentProviderError):
        credit_email.checked({**values, "account": "<b>x</b>"})
    with pytest.raises(PermanentProviderError):
        credit_email.checked({**values, "add_inr": 100})


def test_the_reason_says_how_the_amount_was_worked_out() -> None:
    assert credit_email.reason(_values()) == (
        "About Rs 300 a day over the last 7 days × 14 days left in November = Rs 4,200; "
        "with Rs 800 left, that needs Rs 3,400, rounded up to Rs 3,500."
    )


def test_the_email_says_where_to_pay_how_much_and_that_google_is_the_truth() -> None:
    message = EmailMessage(
        to="admin@authorityclosers.com",
        template=credit_email.TEMPLATE,
        template_version=1,
        idempotency_key="ai-credit-runway:2026-11-17",
        communication_class="verification_security",
        variables={"first_name": "Suyash", **_values()},
    )
    rendered = render_email(message)
    assert rendered.subject == "Gemini credit: about 2 days left, add Rs 3,500"
    for words in (
        "Add Rs 3,500 of Gemini credit",
        "Open Google AI Studio",
        "Billing, then Buy credits",
        "0146E3-722EE0-47B3D5",
        "Google&#39;s figure is the truth",
        credit_email.PAY_URL,
    ):
        assert words in rendered.html
    # The billing page of the prepaid account itself, with Buy credits on it.
    assert credit_email.PAY_URL == (
        "https://aistudio.google.com/billing?billing=0146E3-722EE0-47B3D5"
    )
    assert f'href="{credit_email.PAY_URL}"' in rendered.html
    assert "Rs 800 left" in rendered.text and credit_email.GOOGLE_IS_THE_TRUTH in rendered.text
    # The owner's address only.
    with pytest.raises(PermanentProviderError):
        render_email(
            EmailMessage(
                to="someone@example.com",
                template=credit_email.TEMPLATE,
                template_version=1,
                idempotency_key="ai-credit-runway:2026-11-17",
                communication_class="verification_security",
                variables={"first_name": "Suyash", **_values()},
            )
        )


class _Outbox:
    queued: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, db: Any) -> None:
        del db

    async def enqueue(self, event: Any, *, dedupe_key: str) -> None:
        if any(key == dedupe_key for key, _ in self.queued):
            raise DuplicateIntentError("already queued today")
        self.queued.append((dedupe_key, event.payload))


@pytest.mark.parametrize(
    ("hour_utc", "queued"),
    [(2, 0), (5, 1)],  # 07:30 and 10:30 India time: the day's email waits for 09:00
)
async def test_one_email_a_day_from_nine_india_time(
    monkeypatch: pytest.MonkeyPatch, hour_utc: int, queued: int
) -> None:
    _Outbox.queued = []
    monkeypatch.setattr(credit_runway, "OutboxRepository", _Outbox)
    db = SimpleNamespace()

    @asynccontextmanager
    async def begin():
        yield db

    db.begin = begin

    @asynccontextmanager
    async def sessions():
        yield db

    now = datetime(2026, 11, 17, hour_utc, 0, tzinfo=UTC)
    steps = [step(now - timedelta(days=day, hours=1), 300) for day in range(7)]
    monkeypatch.setattr(
        credit_runway, "read", lambda root, at: runway([export(*steps)], at, TOPUPS)
    )
    for _ in range(2):
        current = await credit_runway.check(sessions, "/store", now)  # type: ignore[arg-type]
        assert current is not None and current.alert
    assert len(_Outbox.queued) == queued
    if queued:
        assert _Outbox.queued[0][0] == "ai-credit-runway:2026-11-17"
