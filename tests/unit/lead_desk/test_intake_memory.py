"""Lead import I2 (owner's picks, 17 Nov 2026): the workspace's earlier choices laid over a
file's guessed columns, and Meta's lead export recognised and cleaned. Made-up values only."""

from uuid import uuid4

from ac_platform.lead_desk.intake_memory import (
    KEEP,
    SKIP,
    Memory,
    is_meta_form,
    meta_cell,
    meta_rows,
    remembered_mapping,
)


def test_remembered_columns_win_over_the_guesses() -> None:
    memory = Memory(columns={"alternate_no": KEEP, "sr_no": SKIP, "naam": "name"})
    mapping, remembered, skip = remembered_mapping(
        ["Sr No", "Naam", "Alternate No", "Mobile"],
        {"phone": "Mobile", "name": "Alternate No"},
        memory,
    )
    assert mapping == {"phone": "Mobile", "name": "Naam"}
    assert remembered == ("Sr No", "Naam", "Alternate No")
    assert skip == ("Sr No",)


def test_memory_reads_words_however_they_are_written() -> None:
    person = uuid4()
    memory = Memory(stages={"call_back": "open_leads"}, owners={"rohit_p": person})
    assert memory.stage("Call  back") == "open_leads"
    assert memory.owner("ROHIT P") == person
    assert memory.stage("Interested") is None


def test_a_facebook_lead_form_export_is_known_and_its_prefixes_come_off() -> None:
    assert is_meta_form(["id", "created_time", "ad_id", "form_id", "full_name"])
    assert is_meta_form(["form_name", "is_organic", "phone_number"])
    assert not is_meta_form(["Name", "Phone", "Form"])
    assert meta_cell("p:+919876075201") == "+919876075201"
    assert meta_cell("l:9001") == "9001"
    # Only Meta's own prefixes, and never an answer's words.
    assert meta_cell("Pune: west") == "Pune: west"
    assert meta_cell("p:") == "p:"
    assert meta_rows([{"phone_number": "p:+91 98760 75201", "city": "Pune"}]) == (
        {"phone_number": "+91 98760 75201", "city": "Pune"},
    )
