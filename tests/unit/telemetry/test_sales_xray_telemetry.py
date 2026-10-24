"""Sales X-Ray product telemetry: the taxonomy, its value checks, call references, admission
and the versioned usage-analytics notice."""

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
    NOTICE_EFFECTIVE_AT,
    NOTICE_V1,
    NOTICE_VERSION,
    NOTICES,
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
_APP = Path(__file__).resolve().parents[3] / "apps" / "sales-xray-web" / "app"
_CLIENT = _APP / "telemetry.ts"


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
            | set(definition.labels)
            | set(definition.flags)
        )
        assert set(definition.allowed_payload_keys) == typed, name
        assert definition.required <= typed, name
        assert {"device", "app", "tier", "net", "link", "app_version"} <= typed, name
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


def test_performance_events_take_bounded_codes_and_numbers_only() -> None:
    timing = SALES_XRAY_EVENTS["sx.action_timing"]
    check_payload_values(
        timing,
        {
            "action": "lead_open",
            "ms": 1840,
            "result": "settled",
            "paint_ms": 96,
            "screen": "leads",
            "tier": "low",
            "net": "slow_2g",
            "link": "cellular",
            "app_version": "0.3.88",
        },
    )
    for bad in (
        {"action": "open_lead", "ms": 10, "result": "settled"},
        {"action": "lead_open", "ms": 60_001, "result": "settled"},
        {"action": "lead_open", "ms": 10, "result": "settled", "app_version": "Beta 2"},
        {"action": "lead_open", "ms": 10, "result": "settled", "tier": "fast"},
    ):
        with pytest.raises(ValueError):
            check_payload_values(timing, bad)
    check_payload_values(
        SALES_XRAY_EVENTS["sx.js_error"],
        {"kind": "error", "error": "typeerror", "where": "e1a2b3c4", "screen": "report"},
    )
    with pytest.raises(ValueError):
        check_payload_values(
            SALES_XRAY_EVENTS["sx.js_error"],
            {"kind": "error", "error": "typeerror", "where": "Cannot read 'x'"},
        )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.api_slow"],
        {"endpoint": "v1_leads_id_calls", "status": "5xx", "ms": 4200},
    )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.screen_viewed"],
        {"screen": "lead", "from": "none", "nav": "first"},
    )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.web_vital"], {"metric": "cls", "value": 120, "rating": "good"}
    )


def test_lead_os_events_take_stage_kinds_and_bands_never_labels() -> None:
    moved = SALES_XRAY_EVENTS["sx.lead_stage_moved"]
    check_payload_values(
        moved,
        {
            "via": "board",
            "source": "ai_suggestion",
            "from_kind": "follow_up",
            "to_kind": "junk",
            "needs": 2,
            "wait": "under_2m",
            "wait_ms": 8_400,
        },
    )
    for bad in (
        {"via": "board"},  # no stage it moved to
        {"via": "board", "to_kind": "Demo Scheduled"},  # a business's own label
        {"via": "drag", "to_kind": "won"},
        {"via": "board", "to_kind": "won", "needs": 5},
    ):
        with pytest.raises(ValueError):
            check_payload_values(moved, bad)
    check_payload_values(SALES_XRAY_EVENTS["sx.board_drag"], {"result": "refused"})
    check_payload_values(
        SALES_XRAY_EVENTS["sx.lead_open_to_action"], {"wait": "2_to_5m", "first": "call"}
    )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.lead_suggestion"], {"action": "accepted", "from": "call"}
    )


def test_the_privacy_page_shows_the_notice_of_the_version_recorded() -> None:
    page = (_APP / "policy-content.tsx").read_text(encoding="utf-8")
    for paragraph in NOTICES[NOTICE_VERSION]:
        assert f'"{paragraph}"' in page
    assert NOTICE_VERSION in page
    assert NOTICE_VERSION == "sx-product-analytics-2026-10-24-v2"
    # v2 (the Android app's signals and Crashlytics) is in force from 04:00 IST, 24 Oct 2026.
    assert NOTICE_EFFECTIVE_AT.isoformat() == "2026-10-23T22:30:00+00:00"
    notice = " ".join(NOTICES[NOTICE_VERSION])
    for never in (
        "call content",
        "lead names",
        "phone numbers",
        "contacts or location",
        "180 days",
    ):
        assert never in notice
    assert "Firebase Crashlytics" in notice
    # v1 stays word for word (supersede, never overwrite).
    assert NOTICES[NOTICE_V1][0].startswith("Sales X-Ray records how its app is used")
    assert "Android" not in " ".join(NOTICES[NOTICE_V1])


def test_android_app_events_take_tiers_and_codes_only() -> None:
    check_payload_values(
        SALES_XRAY_EVENTS["sx.device_profile"],
        {
            "android": 14,
            "maker": "xiaomi",
            "model_label": "m1906g7g",
            "webview": "130",
            "ram_tier": "4",
            "memory_class": 256,
            "low_ram": "no",
            "storage_free": "4to16",
            "app_version": "1.0.26",
            "store": "play",
        },
    )
    for bad in (
        {"model_label": "M1906G7G"},
        {"maker": "Xiaomi Inc"},
        {"ram_tier": "5"},
        {"android": 101},
    ):
        with pytest.raises(ValueError):
            check_payload_values(SALES_XRAY_EVENTS["sx.device_profile"], bad)
    check_payload_values(
        SALES_XRAY_EVENTS["sx.app_launch"], {"start": "cold", "ms": 2_400, "pages": "app"}
    )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.app_frames"],
        {"frames": 5_400, "slow": 120, "frozen": 2, "p90_ms": 24},
    )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.app_exit"], {"reason": "low_memory", "foreground": "no"}
    )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.network_state"],
        {"transport": "cellular", "metered": "yes", "down_tier": "1to5", "cell_gen": "4g"},
    )
    check_payload_values(
        SALES_XRAY_EVENTS["sx.permission_snapshot"],
        {"calls": "granted", "rec_files": "denied", "mic": "not_in_build"},
    )
    # The intake's personal-data guard refuses these key names, so the app uses short ones.
    assert "recordings" not in SALES_XRAY_EVENTS["sx.permission_snapshot"].allowed_payload_keys
    assert "microphone" not in SALES_XRAY_EVENTS["sx.permission_snapshot"].allowed_payload_keys
