"""A lead's "answers from the form": what the person gave, never a source's own ids."""

from ac_platform.lead_desk.store import LeadDesk


def test_answers_leave_out_meta_and_google_references() -> None:
    shown = LeadDesk._source_fields(
        {
            "field_data": [
                {"name": "budget", "values": ["Under 1 crore"]},
                {"name": "full_name", "values": ["Asha Fictional"]},
            ],
            "leadgen_id": "1092411540160157",
            "lead_id": "goog-123",
            "id": "row-9",
            "submission_id": "s-1",
            "meta": {"form_id": "777000111", "ad_id": "1"},
            "lead_source": "Meta · Fictional Homes",
            "_hidden": "x",
        }
    )
    labels = {item.label for item in shown}
    assert labels == {"Budget", "Full name", "Lead source"}
    assert "1092411540160157" not in str(shown)
