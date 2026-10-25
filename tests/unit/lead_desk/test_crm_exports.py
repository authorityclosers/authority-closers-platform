"""Files from other CRMs (universal intake, docs/product/lead-desk/universal-intake.md): each
CRM's export is recognised by its headers and its leads read with no column picked by hand;
a cell with several numbers gives the first; an empty phone column gives way to the next;
owners match by email. Every row here is made up."""

from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.lead_desk.capture import (
    detect_crm,
    extract,
    first_email,
    first_phone,
    key,
    suggest_mapping,
)
from ac_platform.lead_desk.intake import people_index, suggest_columns

# One fictional row per CRM, spelled as its export spells the columns.
EXPORTS: dict[str, dict[str, str]] = {
    "Zoho CRM": {
        "Record Id": "zcrm_5001",
        "Lead Owner": "Seller Example",
        "First Name": "Asha",
        "Last Name": "Example",
        "Company": "Example Solar",
        "Email": "asha@example.com",
        "Phone": "",
        "Mobile": "98760 71001",
        "Lead Status": "Attempted to Contact",
        "City": "Pune",
        "Created Time": "2026-10-01 10:00:00",
    },
    "HubSpot": {
        "Record ID": "101",
        "First Name": "Ravi",
        "Last Name": "Sample",
        "Email": "ravi@example.com",
        "Phone Number": "",
        "Mobile Phone Number": "+91 98760 71002",
        "Contact owner": "Seller Example",
        "Lifecycle Stage": "Lead",
        "Lead Status": "Open",
        "Company Name": "Sample Traders",
        "City": "Nashik",
    },
    "Salesforce": {
        "First Name": "Neha",
        "Last Name": "Demo",
        "Company / Account": "Demo Textiles",
        "Email": "neha@example.com",
        "Phone": "98760 71003",
        "Mobile": "",
        "Lead Status": "Working - Contacted",
        "Lead Owner": "Seller Example",
        "City": "Nagpur",
        "Created Date": "01/10/2026",
    },
    "Pipedrive": {
        "Lead - Title": "Rooftop for a school",
        "Person - Name": "Arjun Sample",
        "Person - Phone": "098760 71004",
        "Person - Email": "arjun@example.com",
        "Organization - Name": "Sample Public School",
        "Lead - Owner": "Seller Example",
    },
    "LeadSquared": {
        "Prospect Id": "p-1",
        "First Name": "Kavya",
        "Last Name": "Example",
        "Email Address": "kavya@example.com",
        "Phone Number": "",
        "Mobile Number": "9876071005",
        "Lead Stage": "Prospect",
        "Owner": "Seller Example",
        "City": "Kolhapur",
        "Created On": "2026-10-02",
    },
    "Kylas": {
        "First Name": "Rahul",
        "Last Name": "Demo",
        "Phone Numbers": "98760 71006, 98760 71099",
        "Emails": "rahul@example.com; rahul.work@example.com",
        "Company Name": "Demo Logistics",
        "Pipeline Stage": "Contacted",
        "Owner": "Seller Example",
        "City": "Aurangabad",
    },
    "Freshsales": {
        "First name": "Pooja",
        "Last name": "Sample",
        "Emails": "pooja@example.com",
        "Mobile": "98760 71007",
        "Work": "",
        "Status": "New",
        "Sales owner": "Seller Example",
        "City": "Satara",
    },
    "LeadRat": {
        "Name": "Sameer Example",
        "Contact No": "98760 71008",
        "Alternate Contact No": "98760 71088",
        "Email": "sameer@example.com",
        "Status": "Site Visit Scheduled",
        "Sub Status": "",
        "Assigned To": "Seller Example",
        "Project": "Example Heights",
        "Location": "Pune",
    },
}


@pytest.mark.parametrize("crm", list(EXPORTS))
def test_each_crm_export_is_recognised_and_read_without_picking_columns(crm: str) -> None:
    row = EXPORTS[crm]
    assert detect_crm(row) == crm
    found = extract(row, suggest_mapping(row))
    assert found.name and found.name.split()[0] in " ".join(row.values())
    assert found.phone is not None and found.phone.startswith("+9198760710")
    assert found.email is not None and found.email.endswith("@example.com")


def test_a_plain_sheet_is_no_crm() -> None:
    assert detect_crm(["Name", "Phone", "Email", "Status", "Owner"]) is None
    assert detect_crm([]) is None


def test_stage_and_owner_columns_of_other_crms() -> None:
    hubspot = EXPORTS["HubSpot"]
    taken = suggest_mapping(hubspot)
    # Lead Status before Lifecycle Stage; the contact owner is the owner.
    assert suggest_columns(hubspot, taken) == {"stage": "Lead Status", "owner": "Contact owner"}
    assert suggest_columns(EXPORTS["Kylas"], suggest_mapping(EXPORTS["Kylas"])) == {
        "stage": "Pipeline Stage",
        "owner": "Owner",
    }
    assert (
        suggest_columns(EXPORTS["Freshsales"], suggest_mapping(EXPORTS["Freshsales"]))["owner"]
        == "Sales owner"
    )


def test_several_numbers_or_emails_in_one_cell_give_the_first() -> None:
    assert first_phone("98760 71006, 98760 71099") == "+919876071006"
    assert first_phone("+91 98760 71006 / +91 98760 71099") == "+919876071006"
    assert first_phone("98760 71006 or 98760 71099") == "+919876071006"
    assert first_phone("not given, 98760 71099") == "+919876071099"
    # One number written with spaces or a slash is still one number.
    assert first_phone("98760  71006") == "+919876071006"
    assert first_phone("022/12345678") == "+912212345678"
    assert first_phone("none") is None
    assert first_email("A@Example.com; b@example.com") == "a@example.com"
    assert first_email("not an email") is None
    assert first_email(None) is None


def test_an_empty_phone_column_gives_way_to_the_next() -> None:
    row = {"Name": "Asha Example", "Phone": "", "Mobile": "98760 71001"}
    found = extract(row, {"name": "Name", "phone": "Phone"})
    assert found.phone == "+919876071001"
    assert found.used["phone"] == "Mobile"
    # A filled chosen column wins.
    row["Phone"] = "98760 71002"
    assert extract(row, {"name": "Name", "phone": "Phone"}).phone == "+919876071002"


def test_owners_match_by_email_as_well_as_name() -> None:
    seller, other = uuid4(), uuid4()
    index = people_index(
        [(seller, "Seller Example"), (other, "Other Person")],
        [(seller, "seller@example.com")],
    )
    assert index[key("seller@example.com")] == seller
    assert index[key("Seller Example")] == seller
    assert index[key("Other")] == other
