"""Lead stages to Meta: every hashed key Sales Xray legitimately holds goes, so Meta's event
match quality can rise; nothing else (no names, notes or call content)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from ac_platform.lead_desk.connectors import meta_capi
from ac_platform.lead_desk.journey.providers import meta, sha256

LEAD = UUID("00000000-0000-4000-8000-0000000000e1")
CREATED = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def lead(**extra: Any) -> Any:
    values = {
        "id": LEAD,
        "source": "meta",
        "source_ref": "120000000000001",
        "email": "Asha@Example.test",
        "phone": "+919876543210",
        "payload": {},
        "created_at": CREATED,
        **extra,
    }
    return SimpleNamespace(**values)


def test_every_hashed_key_we_hold_goes_and_nothing_else() -> None:
    who = meta.identity(lead())
    assert who is not None
    body = meta.body(who, event_name="Site visit booked", at=CREATED)
    user = body["user_data"]
    assert user == {
        "lead_id": 120000000000001,
        "em": [sha256("asha@example.test")],
        "ph": [sha256("919876543210")],
        "external_id": [sha256(str(LEAD))],
        "country": [sha256("in")],
    }
    assert body["event_id"] == meta_capi.event_id("120000000000001", "Site visit booked")
    assert body["action_source"] == "system_generated"
    assert "Asha" not in str(body)


def test_metas_own_click_and_browser_ids_go_when_the_form_kept_them() -> None:
    fbc = "fb.1.1729411200000.IwAR0Fictional123"
    who = meta.identity(lead(payload={"fbc": fbc, "_fbp": "fb.1.1729411200000.1234567890"}))
    assert who is not None and who["fbc"] == fbc and who["fbp"] == "fb.1.1729411200000.1234567890"
    clicked = meta.identity(lead(payload={"fbclid": "IwAR0Fictional123"}))
    assert clicked is not None
    assert clicked["fbc"] == f"fb.1.{int(CREATED.timestamp() * 1000)}.IwAR0Fictional123"
    bad = meta.identity(lead(payload={"fbc": "not a click id", "fbp": "x"}))
    assert bad is not None and "fbc" not in bad and "fbp" not in bad


def test_only_meta_form_leads_go() -> None:
    assert meta.identity(lead(source="webhook")) is None
    assert meta.identity(lead(source_ref="abc")) is None


def test_the_country_comes_from_the_dialling_code() -> None:
    assert meta.country_of("+971501234567") == "ae"
    assert meta.country_of("+919876543210") == "in"
    assert meta.country_of("9876543210") is None
    assert meta.country_of(None) is None


def test_metas_quality_answer_reads_as_a_score_and_key_coverage() -> None:
    answer = {
        "crm": [
            {
                "event_name": "Lead",
                "event_match_quality": {
                    "composite_score": 3.2,
                    "match_key_feedback": [
                        {"identifier": "email", "coverage": {"percentage": 100}},
                        {"identifier": "phone", "coverage": {"percentage": 0}},
                    ],
                },
            },
            {
                "event_name": "Won",
                "event_match_quality": {
                    "composite_score": 5.2,
                    "match_key_feedback": [
                        {"identifier": "phone", "coverage": {"percentage": 40}},
                    ],
                },
            },
        ]
    }
    assert meta.read_quality(answer) == {
        "score": 4.2,
        "events": 2,
        "keys": {"email": 100, "phone": 40},
    }
    assert meta.read_quality({"crm": []}) is None
    assert meta.read_quality({"error": {"code": 100}}) is None
