"""Company-number calls: consented leads only, test phones off production, the spend
guard, the notice, and the ledger's reading of a call."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ac_platform.lead_desk.telephony import ledger, policy
from ac_platform.lead_desk.telephony.http import sign

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
SELLER = uuid4()
ON = policy.CallingSettings(on=True, number="+912000000000", mobiles={str(SELLER): "+919800000001"})
DEV = policy.rules(
    {"AC_TELEPHONY_TEST_NUMBERS": "98000 00001, +91 98000 00002"}, environment="development"
)
PROD = policy.rules({}, environment="production")


def check(
    settings: policy.CallingSettings = ON,
    run: policy.Rules = DEV,
    *,
    source: str = "meta",
    days: float = 1,
    phone: str | None = "+919800000002",
    real: bool = True,
) -> str | None:
    refusal = policy.place_check(settings, run, real_provider=real) or policy.lead_check(
        settings,
        run,
        source=source,
        asked_at=NOW - timedelta(days=days),
        phone=phone,
        now=NOW,
        real_provider=real,
    )
    return refusal.reason if refusal else None


def test_settings_default_to_off_with_the_notice_on_and_consented_sources() -> None:
    value = policy.read({})
    assert value.on is False and value.number is None
    assert value.notice is not None and value.notice.version == policy.DEFAULT_NOTICE
    assert value.sources == ("meta", "webhook") and value.window_days == 7
    stored = policy.as_config(ON)
    again = policy.read({policy.KEY: stored})
    assert again == ON
    # Rubbish in storage reads as the safe defaults.
    odd = policy.read(
        {policy.KEY: {"on": "yes", "window_days": 500, "sources": "all", "number": "x"}}
    )
    assert odd.on is False and odd.window_days == 7 and odd.sources == ("meta", "webhook")
    assert odd.number is None
    with pytest.raises(ValueError):
        policy.as_config(policy.CallingSettings(sources=("everyone",)))


def test_only_leads_who_asked_recently_are_called_from_the_company_number() -> None:
    assert check() is None
    assert check(source="webhook") is None
    # Imported lists and hand-typed numbers stay on the seller's own phone.
    for cold in ("csv", "sheet", "manual", "referral", "synthetic"):
        assert check(source=cold) == "not_asked"
    assert check(days=8) == "too_old"
    assert policy.too_old(1).words.startswith("This lead asked more than 1 day ago")
    wider = replace(ON, window_days=30, sources=("meta", "manual"))
    assert check(wider, days=20, source="manual") is None
    assert check(phone=None) == "no_phone"
    assert check(policy.CallingSettings()) == "off"
    assert check(policy.CallingSettings(on=True)) == "no_number"


def test_off_production_real_calls_reach_only_the_teams_test_phones() -> None:
    assert check(phone="+919811111111") == "test_only"
    # The stand-in rings nobody, so any number is fine with it.
    assert check(phone="+919811111111", real=False) is None
    assert policy.mobile_check(ON, DEV, SELLER, real_provider=True) is None
    stranger = replace(ON, mobiles={str(SELLER): "+919811111111"})
    assert policy.mobile_check(stranger, DEV, SELLER, real_provider=True) == policy.TEST_ONLY
    assert policy.mobile_check(ON, DEV, uuid4(), real_provider=True) == policy.NO_MOBILE


def test_production_places_nothing_until_counsel_has_cleared_it() -> None:
    assert check(run=PROD, phone="+919811111111") == "not_cleared"
    cleared = policy.rules({"AC_TELEPHONY_COUNSEL_CLEARED": "yes"}, environment="production")
    assert check(run=cleared, phone="+919811111111") is None
    tenant = uuid4()
    listed = policy.rules(
        {"AC_TELEPHONY_TENANTS": f"{tenant}, not-a-uuid"}, environment="production"
    )
    assert listed.tenants == frozenset({tenant})


def test_the_spend_guard_counts_30_second_pulses_on_both_legs() -> None:
    assert policy.cost_paise([205, 187], rate_paise=100) == 700  # 7 + 7 pulses of 50 paise
    assert policy.cost_paise([0, 0], rate_paise=100) == 0
    assert policy.cost_paise([1], rate_paise=38) == 19
    cap = policy.limits({}, {})
    assert cap == policy.Limits(500_000, 50_000, 100)
    staff = policy.limits(
        {policy.LIMITS_KEY: {"monthly_paise": 900_000, "rate_paise": 45}},
        {"AC_TELEPHONY_DAILY_CAP_PAISE": "20000"},
    )
    assert staff == policy.Limits(900_000, 20_000, 45)


def test_a_calls_time_limit_is_what_the_budget_left_pays_for() -> None:
    assert policy.time_limit(1_000_000, 100) == policy.MAX_CALL_SECONDS
    assert policy.time_limit(1_000, 100) == 300  # ₹10 left: 5 minutes on two legs
    assert policy.time_limit(150, 100) is None  # under a minute: paused
    cap = policy.Limits(500_000, 50_000, 100)
    assert policy.budget(cap, month_spent=0, day_spent=0) == policy.Budget(50_000, None)
    assert policy.budget(cap, month_spent=0, day_spent=49_900).paused == "day"
    assert policy.budget(cap, month_spent=499_950, day_spent=10_000).paused == "month"


def test_the_notice_is_a_fixed_version_and_the_webhook_address_is_signed() -> None:
    notice = policy.NOTICES[policy.DEFAULT_NOTICE]
    assert notice.text == "This call is recorded, for quality and training."
    tenant, call = uuid4(), uuid4()
    assert sign("s", tenant, call) == sign("s", tenant, call)
    assert sign("s", tenant, call) != sign("t", tenant, call)
    assert sign("s", tenant, call) != sign("s", tenant, uuid4())


def test_the_ledger_folds_a_calls_events_and_counts_what_it_holds() -> None:
    tenant, call_id, lead = uuid4(), uuid4(), uuid4()
    requested = {
        "lead_id": str(lead),
        "seller_person_id": str(SELLER),
        "provider": "exotel",
        "time_limit": 1200,
        "rate_paise": 100,
        "reserve_paise": 2000,
        "notice_version": policy.DEFAULT_NOTICE,
    }
    rows = [(ledger.REQUESTED, requested, NOW)]
    call = ledger.fold(rows, call_id, tenant)
    assert call is not None and call.status == "requested" and not call.final
    assert call.holds(NOW + timedelta(minutes=5)) == 2000
    assert call.holds(NOW + timedelta(hours=3)) == 0  # never heard of again: let go
    rows.append((ledger.PLACED, {"sid": "exo-1", "status": "queued"}, NOW))
    rows.append((ledger.STATUS, {"status": "in_progress", "seller_answered": True}, NOW))
    rows.append(
        (
            ledger.STATUS,
            {
                "status": "completed",
                "lead_answered": True,
                "talk_seconds": 187,
                "cost_paise": 400,
                "recording": True,
                "lead_event_id": str(lead),
            },
            NOW + timedelta(minutes=4),
        )
    )
    # A late, duplicate report changes nothing once the call ended.
    rows.append((ledger.STATUS, {"status": "failed", "cost_paise": 9}, NOW + timedelta(minutes=5)))
    done = ledger.fold(rows, call_id, tenant)
    assert done is not None and done.final and done.status == "completed"
    assert done.sid == "exo-1" and done.talk_seconds == 187 and done.recording
    assert done.holds(NOW) == 400 and done.seller_answered is True
    refused = ledger.fold(
        [
            (ledger.REQUESTED, requested, NOW),
            (ledger.NOT_PLACED, {"words": "Your phone is off."}, NOW),
        ],
        call_id,
        tenant,
    )
    assert refused is not None and refused.final and refused.holds(NOW) == 0
    assert ledger.fold([(ledger.PLACED, {"sid": "x"}, NOW)], call_id, tenant) is None
    assert ledger.tail("+919800000002") == "…0002"
