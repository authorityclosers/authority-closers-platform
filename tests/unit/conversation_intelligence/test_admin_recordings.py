from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence import admin_recordings
from ac_platform.conversation_intelligence.admin_recordings import (
    _cost_view,
    _cursor,
    _decode_cursor,
    _owner_view,
    _provider_stage_view,
    _safe_duration,
    _safe_provider_usage,
    _status,
)
from ac_platform.conversation_intelligence.application import ConversationError


def test_cursor_round_trip_is_opaque_and_stable() -> None:
    created = datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
    recording_id = UUID("11111111-1111-4111-8111-111111111111")
    token = _cursor(created, recording_id)

    assert token != f"{created.isoformat()}|{recording_id}"
    assert _decode_cursor(token) == (created, recording_id)


@pytest.mark.parametrize("token", ["!", "not-a-cursor", "@@@@"])
def test_cursor_rejects_untrusted_values(token: str) -> None:
    with pytest.raises(ConversationError, match="cursor is invalid"):
        _decode_cursor(token)


def test_owner_view_does_not_expose_guest_visitor_identity() -> None:
    recording = SimpleNamespace(person_id=uuid4())
    guest = SimpleNamespace()
    usage = SimpleNamespace(person_id=None, visitor_id=uuid4())

    view = _owner_view(recording, guest, usage, None, {})

    assert view == {
        "kind": "guest",
        "label": "Guest upload",
        "person_id": None,
        "display_name": None,
        "email": None,
        "claimed": False,
    }
    assert "visitor_id" not in view


def test_status_prioritizes_new_held_plan_over_old_report() -> None:
    recording = SimpleNamespace(state="ready")
    run = SimpleNamespace(state="failed")
    plan = SimpleNamespace(state="held")

    assert _status(recording, run, plan, has_report=True) == "held"
    assert _status(recording, run, plan, has_report=False) == "held"
    assert _status(recording, run, None, has_report=False) == "failed"


def test_status_keeps_report_for_newer_native_zero_cost_run() -> None:
    recording = SimpleNamespace(state="ready")
    run = SimpleNamespace(id=uuid4(), state="running")
    report_run_id = uuid4()

    assert (
        _status(
            recording,
            run,
            None,
            has_report=True,
            report_run_id=report_run_id,
            provider_run_ids=frozenset(),
        )
        == "completed"
    )


def test_cost_view_never_invents_actual_cost_without_settlement() -> None:
    view = _cost_view(None, None, None)

    assert view["reservation_paise"] is None
    assert view["estimate_paise"] is None
    assert view["actual_paise"] is None
    assert view["actual_state"] == "not_settled"
    assert view["usage_estimate_paise"] is None
    assert view["usage_estimate_state"] == "not_applicable"


def test_provider_receipt_exposes_allowlisted_usage_without_invoice_claim() -> None:
    task = SimpleNamespace(
        stage="C4",
        state="completed",
        run_id=UUID("33333333-3333-4333-8333-333333333333"),
    )
    job = SimpleNamespace(
        provider_receipt={
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "provider_request_id": "request-1",
            "usage": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 20,
                "untrusted_text": "do-not-expose",
            },
            "cost_state": "reconciliation_required",
            "actual_cost_paise": None,
        }
    )

    view = _provider_stage_view(task, job)

    assert view == {
        "stage": "C4",
        "run_id": "33333333-3333-4333-8333-333333333333",
        "state": "completed",
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "request_id": "request-1",
        "usage": {"promptTokenCount": 100, "candidatesTokenCount": 20},
        "receipt_state": "recorded",
        "cost_state": "reconciliation_required",
        "usage_estimate_paise": 2,
        "usage_estimate_state": "available",
        "usage_estimate_basis": "provider_input_and_output_tokens_x_approved_token_rates",
        "pricing_snapshot": {
            "schema": "ac.sales-xray.pricing-snapshot/1",
            "release_sha": "0847db5d3ca1ed825b68c226713d0f52d11683b1",
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "currency": "INR",
            "usd_to_inr": 100,
            "source_date": "2026-09-14",
            "pricing_ref": "ref:pricing/gemini-38-intro-20260914",
            "evidence_sha256": "d2be76be50be45b17b66aa528eeff86806705bf9e90dce36772c715e3c312fde",
            "source_url": "https://ai.google.dev/gemini-api/docs/latest-model",
            "rate_basis": "per_million_tokens",
            "usd_per_hour": None,
            "input_usd_per_million_tokens": 0.75,
            "output_usd_per_million_tokens": 3.75,
            "is_billing_rate": False,
        },
    }


def test_usage_estimate_requires_a_source_backed_rate() -> None:
    task = SimpleNamespace(
        run_id=uuid4(),
        quote_id=uuid4(),
    )
    view = _cost_view(
        task,
        None,
        None,
        provider_stages=(
            {
                "usage": {"total_tokens": 120},
                "receipt_state": "recorded",
                "usage_estimate_state": "rate_unavailable",
            },
        ),
    )

    assert view["usage_estimate_paise"] is None
    assert view["usage_estimate_state"] == "rate_unavailable"
    assert _safe_provider_usage({"total_tokens": 120, "input": "unsafe"}) == {"total_tokens": 120}


def test_cost_view_aggregates_only_available_stage_estimates() -> None:
    snapshot = {"currency": "INR", "usd_to_inr": 100, "source_date": "2026-09-14"}
    view = _cost_view(
        None,
        None,
        None,
        provider_stages=(
            {
                "usage_estimate_paise": 11,
                "usage_estimate_state": "available",
                "pricing_snapshot": snapshot,
            },
            {
                "usage_estimate_paise": 5,
                "usage_estimate_state": "available",
                "pricing_snapshot": snapshot,
            },
        ),
    )

    assert view["usage_estimate_paise"] == 16
    assert view["usage_estimate_state"] == "available"
    assert view["usage_estimate_currency"] == "INR"
    assert view["usage_estimate_fx_usd_to_inr"] == 100
    assert view["usage_estimate_source_date"] == "2026-09-14"
    assert view["usage_estimate_is_billing_rate"] is False


def test_cost_view_aggregates_latest_plan_stages_from_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_run, second_run = uuid4(), uuid4()
    first_quote, second_quote, scope_id = uuid4(), uuid4(), uuid4()
    first_task = SimpleNamespace(run_id=first_run, quote_id=first_quote)
    second_task = SimpleNamespace(run_id=second_run, quote_id=second_quote)
    quote_rows = {
        first_quote: SimpleNamespace(quote={"max_cost_paise": 1_100}),
        second_quote: SimpleNamespace(quote={"max_cost_paise": 500}),
    }
    first_reservation = SimpleNamespace(
        reservation_id=str(first_run),
        state="reserved",
        quote=SimpleNamespace(max_cost_paise=1_100),
        settlement=None,
    )
    second_reservation = SimpleNamespace(
        reservation_id=str(second_run),
        state="reserved",
        quote=SimpleNamespace(max_cost_paise=500),
        settlement=None,
    )
    monkeypatch.setattr(
        admin_recordings.Quote,
        "from_dict",
        classmethod(lambda _cls, value: SimpleNamespace(max_cost_paise=value["max_cost_paise"])),
    )
    monkeypatch.setattr(
        admin_recordings.BudgetAccount,
        "from_dict",
        classmethod(
            lambda _cls, _value: SimpleNamespace(
                reservations=(first_reservation, second_reservation)
            )
        ),
    )

    view = _cost_view(
        second_task,
        quote_rows[second_quote],
        None,
        plan_tasks=(first_task, second_task),
        quote_rows=quote_rows,
        budget_rows={
            scope_id: SimpleNamespace(scope_id=scope_id, snapshot={}),
        },
    )

    assert view["reservation_paise"] == 1_600
    assert view["estimate_paise"] == 1_600
    assert view["actual_paise"] is None
    assert view["reservation_state"] == "reserved"
    assert view["actual_state"] == "not_settled"


def test_duration_only_accepts_bounded_native_measurement() -> None:
    assert _safe_duration({"media_duration_ms": 12_345}) == 12_345
    assert _safe_duration({"media_duration_ms": 0}) is None
    assert _safe_duration({"media_duration_ms": "12345"}) is None
    assert _safe_duration({"duration_ms": 12_345}) is None
