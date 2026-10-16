"""Google Ads lead form webhooks become one CRM lead; nothing an answer said is lost."""

import pytest

from ac_platform.lead_desk.capture import extract
from ac_platform.lead_desk.connectors.google_ads import (
    LABEL,
    GoogleAdsError,
    google_key,
    to_record,
)

# Google's documented sample shape, with a custom question.
SAMPLE = {
    "lead_id": "TeSter-123-ABCDEFGHIJKLMNOPQRSTUVWXYZ-0123456789-AaBbCcDdEe",
    "user_column_data": [
        {"column_name": "Full Name", "string_value": "Asha Rao", "column_id": "FULL_NAME"},
        {
            "column_name": "User Phone",
            "string_value": "+91 98765 43210",
            "column_id": "PHONE_NUMBER",
        },
        {"column_name": "User Email", "string_value": "Asha@Example.com", "column_id": "EMAIL"},
        {"column_name": "City", "string_value": "Pune", "column_id": "CITY"},
        {"column_name": "Company Name", "string_value": "Rao Solar", "column_id": "COMPANY_NAME"},
        {
            "column_name": "What is your monthly budget?",
            "string_value": "50k-1L",
            "column_id": "budget_q",
        },
    ],
    "api_version": "1.0",
    "form_id": 40000000000,
    "campaign_id": 20000000000,
    "google_key": "source-key-123",
    "is_test": True,
    "gcl_id": "TeSter-123",
    "adgroup_id": 20000000000,
    "creative_id": 30000000000,
}


def test_key_is_the_sources_key() -> None:
    assert google_key(SAMPLE) == "source-key-123"


@pytest.mark.parametrize(
    "bad", [{}, {"google_key": ""}, {"google_key": 5}, {"google_key": "x" * 200}]
)
def test_a_missing_or_odd_key_is_refused(bad: dict) -> None:
    with pytest.raises(GoogleAdsError):
        google_key(bad)


def test_standard_columns_become_the_fields_the_desk_reads() -> None:
    found = extract(to_record(SAMPLE))
    assert found.name == "Asha Rao"
    assert found.phone == "+919876543210"
    assert found.email == "asha@example.com"
    assert found.city == "Pune"
    assert found.company == "Rao Solar"


def test_every_answer_and_googles_ids_are_kept() -> None:
    record = to_record(SAMPLE)
    assert record["What is your monthly budget?"] == "50k-1L"
    assert record["lead_id"] == SAMPLE["lead_id"]
    assert record["google_ads"]["form_id"] == SAMPLE["form_id"]
    assert record["google_ads"]["is_test"] is True
    assert record["lead_source"] == LABEL
    assert "google_key" not in record


def test_first_and_last_name_make_the_name() -> None:
    record = to_record(
        {
            "lead_id": "1",
            "user_column_data": [
                {"column_id": "FIRST_NAME", "column_name": "First Name", "string_value": "Ravi"},
                {"column_id": "LAST_NAME", "column_name": "Last Name", "string_value": "Kumar"},
                {"column_id": "PHONE_NUMBER", "column_name": "Phone", "string_value": "9876543210"},
            ],
        }
    )
    found = extract(record)
    assert found.name == "Ravi Kumar"
    assert found.phone == "+919876543210"


@pytest.mark.parametrize(
    "columns",
    [None, [], "x", [{"column_id": "FULL_NAME", "string_value": "  "}], [5, "x"]],
)
def test_a_lead_with_no_answers_is_refused(columns: object) -> None:
    with pytest.raises(GoogleAdsError):
        to_record({"lead_id": "1", "user_column_data": columns})


def test_columns_and_values_are_bounded() -> None:
    many = [
        {"column_id": f"q{i}", "column_name": f"Question {i}", "string_value": "v" * 5000}
        for i in range(300)
    ]
    record = to_record({"lead_id": "1", "user_column_data": many})
    answers = [name for name in record if name.startswith("Question ")]
    assert len(answers) == 100
    assert all(len(record[name]) == 2000 for name in answers)
