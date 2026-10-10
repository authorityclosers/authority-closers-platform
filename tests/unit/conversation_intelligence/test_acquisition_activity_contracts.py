"""Full wire compatibility and rejection proofs using fictional completed receipts."""

from copy import deepcopy
from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.acquisition_activity_contracts import (
    AccountAcquisitionActivity,
    OrganisationAcquisitionActivity,
)

PERSON_ID = "00000000-0000-0000-0000-000000000001"


def _body(organisation: bool, state: str = "populated") -> dict[str, Any]:
    count, previous, seconds = (2, 1, 90) if state == "populated" else (0, 3, 0)
    if state == "empty":
        previous = 0
    body: dict[str, Any] = {
        "timezone": "Asia/Kolkata",
        "days": [
            {
                "date": (date(2026, 8, 31) + timedelta(days=i)).isoformat(),
                "analysed": count if i == 29 else 0,
                "analysed_seconds": seconds if i == 29 else 0,
            }
            for i in range(30)
        ],
        "analysed_last_30_days": count,
        "analysed_previous_30_days": previous,
    }
    if organisation:
        body["people"] = (
            [
                {
                    "person_id": PERSON_ID,
                    "name": "Fictional Person",
                    "analysed_last_30_days": count,
                    "analysed_seconds_last_30_days": seconds,
                    "analysed_previous_30_days": previous,
                }
            ]
            if state != "empty"
            else []
        )
    return body


def _contract(organisation: bool) -> type[AccountAcquisitionActivity]:
    return OrganisationAcquisitionActivity if organisation else AccountAcquisitionActivity


@pytest.mark.parametrize("organisation", [False, True])
@pytest.mark.parametrize("state", ["populated", "empty", "previous_only"])
def test_exact_response_round_trip(organisation: bool, state: str) -> None:
    body = _body(organisation, state)
    contract = _contract(organisation)
    model = contract.model_validate(body)
    assert model.model_dump(mode="json") == body
    assert contract.model_validate_json(model.model_dump_json()).model_dump(mode="json") == body


@pytest.mark.parametrize(
    ("organisation", "level"),
    [(False, "response"), (False, "day"), (True, "response"), (True, "day"), (True, "person")],
)
@pytest.mark.parametrize("change", ["extra", "missing"])
def test_required_fields_and_no_extras(organisation: bool, level: str, change: str) -> None:
    body = _body(organisation)
    target = body if level == "response" else body["days" if level == "day" else "people"][0]
    if change == "extra":
        target["unexpected"] = 0
        with pytest.raises(ValidationError):
            _contract(organisation).model_validate(body)
    else:
        for key in list(target):
            value = target.pop(key)
            with pytest.raises(ValidationError):
                _contract(organisation).model_validate(body)
            target[key] = value


@pytest.mark.parametrize("organisation", [False, True])
@pytest.mark.parametrize("invalid", [True, "2", 2.0, None, -1])
def test_measurements_are_required_strict_nonnegative_integers(
    organisation: bool, invalid: Any
) -> None:
    paths = [("analysed_last_30_days",), ("analysed_previous_30_days",)]
    paths += [("days", 29, key) for key in ("analysed", "analysed_seconds")]
    if organisation:
        paths += [
            ("people", 0, key)
            for key in (
                "analysed_last_30_days",
                "analysed_seconds_last_30_days",
                "analysed_previous_30_days",
            )
        ]
    for path in paths:
        body = _body(organisation)
        target = body
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = invalid
        with pytest.raises(ValidationError):
            _contract(organisation).model_validate(body)


@pytest.mark.parametrize("organisation", [False, True])
@pytest.mark.parametrize("invalid", ["2026-02-30", "2026-9-29", "2026-09-29T00:00:00", 1, None])
def test_invalid_date_representations(organisation: bool, invalid: Any) -> None:
    body = _body(organisation)
    body["days"][-1]["date"] = invalid
    with pytest.raises(ValidationError):
        _contract(organisation).model_validate(body)


@pytest.mark.parametrize("invalid", ["bad-id", PERSON_ID.replace("-", ""), 1, None])
def test_invalid_uuid_representations(invalid: Any) -> None:
    body = _body(True)
    body["people"][0]["person_id"] = invalid
    with pytest.raises(ValidationError):
        OrganisationAcquisitionActivity.model_validate(body)


@pytest.mark.parametrize("organisation", [False, True])
@pytest.mark.parametrize("change", ["short", "long", "reverse", "duplicate", "gap", "total"])
def test_days_count_order_and_total(organisation: bool, change: str) -> None:
    body = _body(organisation)
    if change == "short":
        body["days"].pop()
    elif change == "long":
        body["days"].append(deepcopy(body["days"][-1]))
    elif change == "reverse":
        body["days"].reverse()
    elif change == "duplicate":
        body["days"][1]["date"] = body["days"][0]["date"]
    elif change == "gap":
        body["days"][-1]["date"] = "2026-09-30"
    else:
        body["analysed_last_30_days"] += 1
    with pytest.raises(ValidationError):
        _contract(organisation).model_validate(body)


@pytest.mark.parametrize(
    "key", ["analysed_last_30_days", "analysed_previous_30_days", "analysed_seconds_last_30_days"]
)
def test_people_totals_match_response_and_days(key: str) -> None:
    body = _body(True)
    body["people"][0][key] += 1
    with pytest.raises(ValidationError):
        OrganisationAcquisitionActivity.model_validate(body)


@pytest.mark.parametrize("change", ["duplicate", "order", "name_type", "timezone"])
def test_people_order_identity_and_other_scalar_types(change: str) -> None:
    body = _body(True)
    if change in {"duplicate", "order"}:
        person = deepcopy(body["people"][0])
        person.update(
            analysed_last_30_days=0, analysed_seconds_last_30_days=0, analysed_previous_30_days=0
        )
        if change == "order":
            person.update(name="Alex", person_id="00000000-0000-0000-0000-000000000002")
        body["people"].append(person)
    elif change == "name_type":
        body["people"][0]["name"] = 12
    else:
        body["timezone"] = "UTC"
    with pytest.raises(ValidationError):
        OrganisationAcquisitionActivity.model_validate(body)


@pytest.mark.parametrize("organisation", [False, True])
def test_schema_has_exact_required_fields_and_wire_constraints(organisation: bool) -> None:
    schema = _contract(organisation).model_json_schema()
    assert set(schema["properties"]) == set(schema["required"]) == set(_body(organisation))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["days"]["minItems"] == 30
    assert schema["properties"]["days"]["maxItems"] == 30
    assert schema["properties"]["timezone"]["const"] == "Asia/Kolkata"
    day = schema["$defs"]["CompletedReceiptDay"]
    assert set(day["properties"]) == set(day["required"]) == set(_body(False)["days"][0])
    assert day["properties"]["date"]["format"] == "date"
    models = [schema, day]
    if organisation:
        person = schema["$defs"]["CompletedReceiptPerson"]
        assert set(person["properties"]) == set(person["required"]) == set(_body(True)["people"][0])
        assert person["properties"]["person_id"]["format"] == "uuid"
        models.append(person)
    for model in models:
        assert model["additionalProperties"] is False
        for name, field in model["properties"].items():
            if name.startswith("analysed"):
                assert field["type"] == "integer" and field["minimum"] == 0
