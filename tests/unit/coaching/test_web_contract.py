"""The web parsers read exactly what the Coaching API serializes.

The checked-in JSON is the API's own output for fictional call, My and Team
views; `app/coaching/server-contract.test.ts` parses the same file. A field
change on either side fails one of the two tests. Regenerate after an
intended contract change with ``AC_UPDATE_COACHING_CONTRACT=1``, then run
Prettier on the JSON (the comparison is semantic, so layout never matters).
"""

import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from ac_platform.coaching.call import build_call_coaching
from ac_platform.coaching.contracts import CallSummary, ObjectionSeen
from ac_platform.coaching.learner import build_learner
from ac_platform.coaching.report_adapter import from_report
from ac_platform.coaching.team import summarize_team
from tests.unit.coaching.test_report_adapter import CALL, NOW, envelope

FIXTURE = (
    Path(__file__).resolve().parents[3] / "apps/sales-xray-web/app/coaching/server-contract.json"
)
PERSON, TENANT, SESSION = UUID(int=1), UUID(int=2), UUID(int=3)


def _report() -> dict[str, Any]:
    data = envelope()
    report = data["report"]["content"]
    ref = {"segment_id": "seg-2", "quote": "Tell me more.", "start_ms": 4000, "end_ms": 6000}
    report["strengths"] = [
        {"title": "Curious follow-up", "explanation": "You asked a follow-up.", "evidence": [ref]}
    ]
    report["missed_opportunities"] = [
        {"title": "Ask for the next step", "explanation": "Book a date.", "evidence": [ref]}
    ]
    return data


def _views() -> dict[str, Any]:
    data = _report()
    call = build_call_coaching(
        data, submission_id=CALL, created_at=NOW, person_id=PERSON, tenant_id=TENANT
    )
    history = from_report(data, submission_id=CALL, created_at=NOW, comparison_key="v1")
    assert history is not None
    mine = build_learner((history,), person_id=PERSON, tenant_id=TENANT).model_copy(
        update={
            "calls": (
                CallSummary(
                    submission_id=CALL,
                    call_label="Fictional sales call",
                    created_at=NOW,
                    state="ready",
                    focus_label="Impact clarity",
                ),
            )
        }
    )
    heard = history.model_copy(
        update={
            "has_call_map": True,
            "objections": (
                ObjectionSeen(kind="price_concern", handling="answered"),
                ObjectionSeen(kind="price_concern", handling="ignored"),
            ),
        }
    )
    team = summarize_team(((UUID(int=9), heard),), person_id=PERSON, tenant_id=TENANT)
    # The HTTP layer stamps the reading session on every view.
    return {
        name: view.model_copy(update={"session_id": SESSION}).model_dump(mode="json", by_alias=True)
        for name, view in (("call", call), ("me", mine), ("team", team))
    }


def test_the_web_contract_fixture_is_the_apis_own_output() -> None:
    views = _views()
    assert views["call"]["strength"]["title"] == "Curious follow-up"
    assert views["call"]["other_suggestions"] == 1
    assert views["me"]["strength"]["title"] == "Curious follow-up"
    if os.environ.get("AC_UPDATE_COACHING_CONTRACT") == "1":
        FIXTURE.write_text(json.dumps(views, indent=2, sort_keys=True) + "\n")
    assert json.loads(FIXTURE.read_text()) == views
