"""Prepared commands pin a link/stage; they never grant authority or infer facts."""

from dataclasses import FrozenInstanceError
from typing import Any
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.prospect_call_outcome import (
    MAX_SAFE_REVISION,
    HumanOutcome,
    HumanOutcomeCommand,
    OutcomeValidationError,
)

MEMBERSHIP = UUID("00000000-0000-4000-8000-000000000006")


def command() -> dict[str, Any]:
    return {
        "value": {
            "outcome": "lost",
            "lost_reason": "दूसरा विकल्प चुना।",
            "deal_value": {"amount": "125000.0000", "currency_code": "INR"},
        },
        "expected_revision": 0,
        "expected_membership_id": str(MEMBERSHIP),
        "expected_prospect_stage_revision": 2,
    }


@pytest.mark.parametrize("linked", [True, False])
def test_literal_command_and_three_fences_round_trip(linked: bool) -> None:
    payload = command()
    if not linked:
        payload.update(expected_membership_id=None, expected_prospect_stage_revision=None)
    value = HumanOutcomeCommand.parse(payload)
    assert value.json() == {**payload, "value": HumanOutcome.parse(payload["value"]).json()}
    assert HumanOutcomeCommand.parse(value.json()) == value


@pytest.mark.parametrize(
    "field",
    ["value", "expected_revision", "expected_membership_id", "expected_prospect_stage_revision"],
)
def test_all_command_fences_are_explicit(field: str) -> None:
    payload = command()
    del payload[field]
    with pytest.raises(OutcomeValidationError, match="invalid_outcome_command_fields"):
        HumanOutcomeCommand.parse(payload)


@pytest.mark.parametrize(
    "field", ["actor_id", "tenant_id", "session_id", "can_edit", "stage", "role"]
)
def test_browser_authority_or_inferred_stage_is_not_a_command_field(field: str) -> None:
    payload = {**command(), field: "private supplied authority"}
    with pytest.raises(OutcomeValidationError) as caught:
        HumanOutcomeCommand.parse(payload)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "revision", [None, True, 1.0, -1, MAX_SAFE_REVISION, MAX_SAFE_REVISION + 1]
)
def test_outcome_revision_never_coerces_or_overflows(revision: object) -> None:
    with pytest.raises(OutcomeValidationError, match="invalid_expected_outcome_revision"):
        HumanOutcomeCommand.parse({**command(), "expected_revision": revision})


@pytest.mark.parametrize("revision", [None, True, 1.0, -1, MAX_SAFE_REVISION + 1])
def test_linked_stage_revision_is_exact(revision: object) -> None:
    with pytest.raises(OutcomeValidationError, match="invalid_expected_prospect_binding"):
        HumanOutcomeCommand.parse({**command(), "expected_prospect_stage_revision": revision})


@pytest.mark.parametrize(
    "membership",
    [
        False,
        1,
        "../other",
        "private invalid identifier",
        str(MEMBERSHIP).replace("-", ""),
        MEMBERSHIP,
    ],
)
def test_membership_is_a_canonical_wire_uuid(membership: object) -> None:
    with pytest.raises(OutcomeValidationError) as caught:
        HumanOutcomeCommand.parse({**command(), "expected_membership_id": membership})
    assert "private" not in str(caught.value)


def test_unlinked_does_not_accept_or_invent_a_stage_revision() -> None:
    with pytest.raises(OutcomeValidationError, match="invalid_expected_prospect_binding"):
        HumanOutcomeCommand.parse({**command(), "expected_membership_id": None})


@pytest.mark.parametrize(
    "value", [None, {"outcome": "lost"}, {"outcome": "won", "basis": "heard_in_call"}]
)
def test_no_clear_or_ai_value_can_enter_the_human_command(value: object) -> None:
    with pytest.raises(OutcomeValidationError):
        HumanOutcomeCommand.parse({**command(), "value": value})


def test_command_detaches_mutable_request_and_stays_immutable() -> None:
    payload = command()
    value = HumanOutcomeCommand.parse(payload)
    expected = value.json()
    payload["value"]["deal_value"]["amount"] = "1"
    payload["expected_prospect_stage_revision"] = 9
    assert value.json() == expected
    with pytest.raises(FrozenInstanceError):
        value.expected_revision = 9  # type: ignore[misc]


def test_direct_construction_has_the_wire_revision_and_link_guards() -> None:
    value = HumanOutcome("won")
    assert HumanOutcomeCommand(value, 0, None, None).json()["expected_membership_id"] is None
    with pytest.raises(OutcomeValidationError):
        HumanOutcomeCommand(value, True, None, None)
    with pytest.raises(OutcomeValidationError):
        HumanOutcomeCommand(value, 0, MEMBERSHIP, None)
    with pytest.raises(OutcomeValidationError):
        HumanOutcomeCommand(value, 0, None, 0)
