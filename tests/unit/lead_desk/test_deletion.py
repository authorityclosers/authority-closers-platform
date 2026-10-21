"""Deleting chosen leads (owner, 21 Oct 2026): command shapes and the SQL that empties
what other parts keep. The PostgreSQL journey is tests/database/test_lead_desk_delete_postgresql.py.
"""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.dialects import postgresql

from ac_platform.lead_desk import deletion
from ac_platform.lead_desk.contracts import DeleteLead, DeleteLeads, LeadsDeleted
from ac_platform.lead_desk.models import LeadConversion
from ac_platform.partner_events.models import PartnerLeadEvent


def test_one_confirm_deletes_one_to_five_hundred_leads() -> None:
    command = uuid4()
    assert DeleteLeads(command_id=command, lead_ids=(uuid4(),)).command_id == command
    DeleteLeads(command_id=command, lead_ids=tuple(uuid4() for _ in range(deletion.MAX_LEADS)))
    for lead_ids in ((), tuple(uuid4() for _ in range(deletion.MAX_LEADS + 1))):
        with pytest.raises(ValidationError):
            DeleteLeads(command_id=command, lead_ids=lead_ids)
    with pytest.raises(ValidationError):
        DeleteLeads.model_validate({"command_id": str(command), "lead_ids": [str(uuid4())], "x": 1})
    with pytest.raises(ValidationError):
        DeleteLead.model_validate({})


def test_the_answer_names_ids_and_counts_only() -> None:
    lead = uuid4()
    answer = LeadsDeleted(deleted=1, lead_ids=(lead,), not_found=0)
    assert answer.model_dump(mode="json", by_alias=True) == {
        "schema": "lead-desk/1",
        "deleted": 1,
        "lead_ids": [str(lead)],
        "not_found": 0,
    }


def _sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_a_row_a_sender_holds_is_skipped_never_waited_on() -> None:
    sql = _sql(
        update(LeadConversion)
        .where(deletion._free(LeadConversion, uuid4(), [uuid4()]))
        .values(**deletion._dropped(LeadConversion, ("pending",)))
    )
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "lead_desk_conversions.lead_id IN" in sql
    assert "lead_desk_conversions.tenant_id =" in sql


def test_a_waiting_send_is_dropped_as_lead_gone() -> None:
    values = deletion._dropped(PartnerLeadEvent, ("pending", "dead_letter"))
    assert values["payload"] is None
    status = _sql(values["status"])
    assert "CASE WHEN" in status and "partner_lead_events.status IN" in status
    assert deletion.GONE == "lead_gone"
