"""Reject crossed evidence before building a learner projection."""

from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.coaching.contracts import CallHistory
from tests.unit.coaching.test_learner import call


@pytest.mark.parametrize("change", ["source", "call", "skill", "mission", "duplicate"])
def test_call_mission_and_skill_must_keep_one_source_binding(change: str) -> None:
    data = call(1).model_dump(mode="json")
    skill = data["skills"][0]
    if change == "source":
        skill["evidence"][0]["source_sha256"] = "a" * 64
    elif change == "call":
        skill["evidence"][0]["submission_id"] = str(UUID(int=999))
    elif change == "skill":
        skill["mission"]["skill_id"] = "qualification"
    elif change == "mission":
        skill["mission"]["origin_submission_id"] = str(UUID(int=999))
    else:
        data["skills"].append(deepcopy(skill))
    with pytest.raises(ValidationError):
        CallHistory.model_validate(data)
