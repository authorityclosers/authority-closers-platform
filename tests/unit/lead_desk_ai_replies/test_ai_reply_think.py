"""AI replies: the model is asked only when the rules allow, and its draft is checked."""

import asyncio
import json
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.lead_desk.ai_replies import prompt, service
from tests.unit.lead_desk_ai_replies.businesses import CASES, HOMES, MODEL_CASES, Case


class ScriptedModel:
    """Answers like a well-behaved model would, from the case's expectation."""

    def __init__(self, answer: dict[str, Any] | Exception | None = None) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    async def complete(self, *, tenant_id: UUID, system: str, user: str) -> service.Completion:
        self.asked.append((system, user))
        if isinstance(self.answer, Exception):
            raise self.answer
        return service.Completion(
            text=json.dumps(
                self.answer or {"reply": "Yes, every day 10am to 7pm.", "handoff": False}
            ),
            provider="fake",
            model="fake-small",
            input_tokens=420,
            output_tokens=30,
            cost_inr=Decimal("0.0123"),
            usage_ref="usage-1",
        )


def ready(case: Case, *, window: bool = True) -> service.Prepared:
    return service.Prepared(
        tenant_id=uuid4(),
        lead_id=uuid4(),
        lead_name="Asha Fictional",
        owner_person_id=None,
        payload=None,
        channel="whatsapp",
        account_id=None,
        settings=case.business,
        turns=[prompt.Turn("in", case.message)],
        last_in_id=uuid4(),
        last_in_text=case.message,
        window_open=window,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.message[:40])
def test_hand_offs_and_stops_never_reach_the_model(case: Case) -> None:
    model = ScriptedModel()
    result = asyncio.run(service.think(model, ready(case)))
    if case.expect == "reply":
        assert result.outcome == "drafted" and result.draft
        assert len(model.asked) == 1
    elif case.expect == "opt_out":
        assert (result.outcome, model.asked) == ("opted_out", [])
    else:
        assert (result.outcome, result.reason, model.asked) == ("handoff", case.expect, [])


@pytest.mark.parametrize("case", MODEL_CASES, ids=lambda case: case.message[:40])
def test_the_models_own_hand_off_is_kept(case: Case) -> None:
    model = ScriptedModel({"reply": "", "handoff": True, "reason": case.expect})
    result = asyncio.run(service.think(model, ready(case)))
    assert (result.outcome, result.reason) == ("handoff", case.expect)
    assert result.completion is not None and result.completion.model == "fake-small"


def test_a_draft_that_breaks_a_rule_is_not_used_but_its_cost_is_kept() -> None:
    model = ScriptedModel(
        {"reply": "The 3 BHK is ₹92 lakh, call +91 90000 11111.", "handoff": False}
    )
    result = asyncio.run(service.think(model, ready(Case(HOMES, "Is the 3 BHK ready?", "reply"))))
    assert (result.outcome, result.reason) == ("handoff", "blocked_reply")
    row = service.audit(ready(Case(HOMES, "x", "reply")), result, mode="auto", now=_now())
    assert (row.outcome, row.draft, row.input_tokens, row.cost_inr) == (
        "handoff",
        None,
        420,
        Decimal("0.0123"),
    )


def test_no_model_or_no_budget_pauses_without_a_reply() -> None:
    case = Case(HOMES, "Site visit on Sunday?", "reply")
    paused = asyncio.run(
        service.think(ScriptedModel(service.ModelUnavailable("budget", "cap")), ready(case))
    )
    assert (paused.outcome, paused.reason) == ("paused", "budget")
    failed = asyncio.run(
        service.think(ScriptedModel(service.ModelUnavailable("failed", "down")), ready(case))
    )
    assert (failed.outcome, failed.reason) == ("failed", "failed")


def test_outside_the_window_nothing_is_asked() -> None:
    model = ScriptedModel()
    result = asyncio.run(
        service.think(model, ready(Case(HOMES, "Site visit on Sunday?", "reply"), window=False))
    )
    assert (result.outcome, result.reason, model.asked) == ("handoff", "window", [])


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)
