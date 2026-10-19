"""Lead events and customer hand-overs: the rules that need no database (0102, fictional data)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from ac_platform.partner_events.lead_events import (
    Answer,
    Context,
    LeadFieldsError,
    capacity_kw,
    consent_granted,
    handover_request,
    read_answer,
    validate_lead_fields,
    wanted,
)

AT = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
TENANT = UUID("00000000-0000-4000-8000-000000000001")
LEAD = UUID("00000000-0000-4000-8000-000000000002")


def context(phone: str = "+919999900001", answers: dict[str, str] | None = None) -> Context:
    return Context(
        tenant_id=TENANT,
        lead={
            "id": LEAD,
            "name": "Customer Example",
            "phone": phone,
            "email": "customer@example.test",
            "city": "Pune",
            "source": "meta",
            "source_label": "Example form",
            "created_at": AT,
            "test_data": False,
        },
        event={"kind": "result", "data": {"from_stage": "new", "stage": "won"}, "created_at": AT},
        answers={key: Answer(value, AT) for key, value in (answers or {}).items()},
        owner={"id": TENANT, "name": "Seller Example", "email": "seller@example.test"},
        actor=None,
        reopened_from=None,
        stages=[("new", AT), ("won", AT)],
        calls=[],
    )


@pytest.mark.parametrize(
    ("said", "kw"),
    [
        ("5", 5),
        ("5 kW", 5),
        ("5.5kw", 5.5),
        ("3.25 KWp", 3.25),
        ("five", None),
        ("5-6 kW", None),
        ("0", None),
    ],
)
def test_capacity_is_read_only_from_a_plain_number(said: str, kw: float | None) -> None:
    assert capacity_kw(said) == kw


@pytest.mark.parametrize(
    ("said", "granted"), [("Yes", True), ("I agree", True), ("No", False), ("maybe", None)]
)
def test_consent_is_read_only_from_a_clear_answer(said: str, granted: bool | None) -> None:
    assert consent_granted(said) is granted


def test_the_smallest_hand_over_carries_only_the_required_parts() -> None:
    built = handover_request(
        context(answers={"Address": "12 Example Lane"}),
        app_url="http://localhost:3000",
        approved=None,
    )
    assert built.problems == []
    assert built.body == {
        "source": {"system": "sales_xray", "accountId": str(TENANT), "leadId": str(LEAD)},
        "customer": {"name": "Customer Example", "phone": "+919999900001"},
        "closing": {"closedAt": "2026-10-19T09:00:00Z"},
    }


def test_only_approved_parts_and_questions_are_sent() -> None:
    approved = validate_lead_fields(
        {"send": ["requirement"], "questions": {"requirement.system_type": "System type"}},
        "handover",
    )
    built = handover_request(
        context(
            answers={"System type": "On-grid", "Address": "12 Example Lane", "Pincode": "411038"}
        ),
        app_url="https://xray.example.test",
        approved=approved,
    )
    assert built.body["requirement"] == {"systemType": "On-grid"}
    assert "address" not in built.body["customer"] and "email" not in built.body["customer"]


def test_an_address_without_a_valid_pin_code_is_left_out() -> None:
    approved = validate_lead_fields(
        {
            "send": ["address"],
            "questions": {"address.line1": "Address", "address.pin_code": "Pincode"},
        },
        "handover",
    )
    built = handover_request(
        context(answers={"Address": "12 Example Lane", "Pincode": "41103"}),
        app_url="https://xray.example.test",
        approved=approved,
    )
    assert "address" not in built.body["customer"]


def test_a_phone_that_is_not_e164_is_a_problem_before_sending() -> None:
    built = handover_request(
        context(phone="+91 99999 00003"), app_url="https://x.test", approved=None
    )
    assert built.problems == [{"path": "/customer/phone", "problem": "not E.164"}]


@pytest.mark.parametrize(
    "value",
    [
        {"send": ["notes"]},
        {"send": [], "questions": {"address.line1": "Address"}},
        {
            "send": ["consents"],
            "consents": [{"question": "Q", "purpose": "sales", "channel": "sms"}],
        },
        {"send": ["address"], "questions": {"customer.secret": "Q"}},
        {"other": 1},
    ],
)
def test_invalid_approvals_are_refused(value: object) -> None:
    with pytest.raises(LeadFieldsError):
        validate_lead_fields(value, "handover")


def test_a_webhook_takes_no_form_answers() -> None:
    with pytest.raises(LeadFieldsError, match="only_for_handover"):
        validate_lead_fields({"send": []}, "webhook")


def test_what_each_lead_desk_event_becomes() -> None:
    every = ["lead.handover", "lead.created", "lead.stage_changed", "lead.closed"]
    won = {"kind": "result", "data": {"from_stage": "interested", "stage": "won"}}
    reopen = {"kind": "repeat", "data": {"reopened": True}}
    assert wanted("handover", won, every) == ["lead.handover"]
    assert wanted("webhook", won, every) == ["lead.stage_changed", "lead.closed"]
    assert wanted("handover", reopen, every) == []  # a reopen alone sends no hand-over
    assert wanted("webhook", reopen, every) == ["lead.stage_changed"]
    same = {"kind": "result", "data": {"from_stage": "won", "stage": "won"}}
    assert wanted("handover", same, every) == []


def test_the_partners_answer_is_read_without_its_body() -> None:
    assert read_answer(
        201, b'{"customerId":null,"customerCode":"XX-000142","result":"created"}'
    ) == (
        "created",
        "XX-000142",
        None,
    )
    assert read_answer(202, b"not json") == (None, None, None)
    _, _, rejection = read_answer(
        422, b'{"error":"invalid","fields":[{"path":"/customer/phone","problem":"not E.164"}]}'
    )
    assert rejection == {
        "by": "partner",
        "http_status": 422,
        "error": "invalid",
        "fields": [{"path": "/customer/phone", "problem": "not E.164"}],
    }
    assert read_answer(503, b"{}") == (None, None, None)
