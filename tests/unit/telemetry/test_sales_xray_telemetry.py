"""Sales X-Ray product telemetry: the taxonomy, its value checks, call references, admission."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.telemetry.ingest import (
    LEARNER_PRODUCT_ANALYTICS_EVENTS,
    LEARNER_SURFACE,
    check_payload_values,
)
from ac_platform.telemetry.sales_xray import (
    MAX_DWELL_MS,
    RETENTION_DAYS,
    RETENTION_POLICY_ID,
    SALES_XRAY_EVENTS,
    SALES_XRAY_SURFACE,
    SKILLS,
    SalesXrayAdmission,
    call_ref,
)
from ac_platform.usage_people.pseudonyms import pads

_PII_KEY = re.compile(
    r"(?:email|e[-_ ]?mail|phone|mobile|address|name|transcript|audio|recording|"
    r"token|secret|password|ip|device.?id|cookie|prompt|answer|message|url)",
    re.IGNORECASE,
)
_CLIENT = Path(__file__).resolve().parents[3] / "apps" / "sales-xray-web" / "app" / "telemetry.ts"


def test_every_client_event_is_in_the_server_taxonomy_and_only_sales_xray_events_are() -> None:
    source = _CLIENT.read_text(encoding="utf-8")
    listed = re.search(r"TELEMETRY_EVENT_NAMES = \[(.*?)\]", source, re.DOTALL)
    assert listed is not None
    client_names = set(re.findall(r'"(sx\.[a-z_]+)"', listed.group(1)))
    assert client_names == set(SALES_XRAY_EVENTS)
    assert not set(SALES_XRAY_EVENTS) & set(LEARNER_PRODUCT_ANALYTICS_EVENTS)
    assert SALES_XRAY_SURFACE.routes.isdisjoint({"/home", "/progress"})
    assert "/analysis/calls/[callId]" in SALES_XRAY_SURFACE.routes
    assert LEARNER_SURFACE.events is LEARNER_PRODUCT_ANALYTICS_EVENTS


def test_every_key_is_typed_and_none_could_carry_a_person() -> None:
    for name, definition in SALES_XRAY_EVENTS.items():
        typed = (
            set(definition.values)
            | set(definition.numbers)
            | set(definition.tokens)
            | set(definition.flags)
        )
        assert set(definition.allowed_payload_keys) == typed, name
        assert definition.required <= typed, name
        assert {"device", "app"} <= typed, name
        for key in typed:
            assert not _PII_KEY.search(key), (name, key)
    calls = {name for name, definition in SALES_XRAY_EVENTS.items() if definition.takes_call}
    assert calls == {
        "sx.report_opened",
        "sx.section_read",
        "sx.section_action",
        "sx.on_demand_requested",
        "sx.full_report_requested",
        "sx.reanalyse_requested",
        "sx.outcome_set",
    }
    assert {f"d{number:02d}" for number in range(1, 19)} == SKILLS
    assert RETENTION_DAYS == 180
    assert RETENTION_POLICY_ID == "sx-product-analytics-v1"


def test_values_are_checked_by_type() -> None:
    read = SALES_XRAY_EVENTS["sx.section_read"]
    check_payload_values(
        read,
        {
            "section": "analysis",
            "skill": "d07",
            "look": "brain4",
            "read_band": "5_30s",
            "dwell_ms": 4200,
            "device": "phone",
            "app": "android",
        },
    )
    check_payload_values(
        read, {"section": "prospect-information", "read_band": "over_120s", "dwell_ms": 600_000}
    )
    assert MAX_DWELL_MS == 600_000
    for bad in (
        {"read_band": "5_30s"},  # no section
        {"section": "analysis"},  # no band
        {"section": "Analysis", "read_band": "5_30s"},  # not one of the values
        {"section": "summary", "read_band": "5_30s"},
        {"section": "analysis", "read_band": "5_30s", "dwell_ms": MAX_DWELL_MS + 1},
        {"section": "analysis", "read_band": "5_30s", "dwell_ms": -1},
        {"section": "analysis", "read_band": "5_30s", "dwell_ms": True},
        {"section": "analysis", "read_band": "5_30s", "dwell_ms": "4200"},
        {"section": "analysis", "read_band": "5_30s", "skill": "D07"},
        {"section": "analysis", "read_band": "5_30s", "skill": "d19"},
        {"section": "analysis", "read_band": "5_30s", "device": "watch"},
    ):
        with pytest.raises(ValueError):
            check_payload_values(read, bad)
    check_payload_values(
        SALES_XRAY_EVENTS["sx.on_demand_requested"], {"section": "analysis", "level": "data_only"}
    )
    with pytest.raises(ValueError):
        check_payload_values(
            SALES_XRAY_EVENTS["sx.section_action"], {"section": "analysis", "action": "share"}
        )
    shown = SALES_XRAY_EVENTS["sx.error_shown"]
    check_payload_values(shown, {"surface": "recent_calls", "code": "section_failed"})
    for bad_code in ("Read failed", "read-failed", "x" * 49, "", "9lives"):
        with pytest.raises(ValueError):
            check_payload_values(shown, {"surface": "connection_card", "code": bad_code})


def test_a_call_reference_is_a_keyed_hash_of_the_recording_apart_from_person_pseudonyms() -> None:
    key = os.urandom(32)
    inner, outer = pads(key)
    recording = uuid4()
    reference = call_ref(inner, outer, recording)
    expected = hmac.new(key, f"call:{recording}".encode(), hashlib.sha256).hexdigest()[:16]
    assert reference == "c_" + expected
    assert call_ref(inner, outer, str(recording)) == reference
    other_inner, other_outer = pads(os.urandom(32))
    assert call_ref(other_inner, other_outer, recording) != reference
    # Domain-separated from a person pseudonym of the same id.
    person = hmac.new(key, str(recording).encode(), hashlib.sha256).hexdigest()[:16]
    assert expected != person


def test_admission_caps_each_workspace_per_minute() -> None:
    now = [0.0]
    admission = SalesXrayAdmission(per_minute=50, clock=lambda: now[0])
    first, second = uuid4(), uuid4()
    assert admission.admit(tenant_id=first, event_count=40, payload_bytes=1000)
    assert not admission.admit(tenant_id=first, event_count=11, payload_bytes=1000)
    assert admission.admit(tenant_id=second, event_count=50, payload_bytes=1000)
    now[0] = 60.0
    assert admission.admit(tenant_id=first, event_count=50, payload_bytes=1000)
