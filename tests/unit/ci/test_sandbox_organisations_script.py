"""The sandbox organisations' plan is realistic and clearly fictional (owner, 30 Oct 2026:
two test organisations with 30 days of work, docs/product/lead-desk/stages-views-sources.md,
section 7): the input is checked, every seller signs in with a plus-alias of the owner's
mailbox, no lead number can ring anyone, and a seller's day runs 10:30 to 19:00 with lunch
and, for some, an unexplained gap."""

import importlib.util
import json
import sys
from collections import Counter
from datetime import date, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from ac_platform.identity.password_auth import verify_password
from ac_platform.lead_desk.capture import normalise_phone

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, file: str):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, ROOT / "scripts/data-changes" / file)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


change = _load("sandbox_organisations", "sandbox-organisations.py")
logins_tool = _load("sandbox_logins", "sandbox-logins.py")

IST = ZoneInfo("Asia/Kolkata")
SEED = UUID(int=30_10_2026)
VERIFIER = "scrypt$ln=15,r=8,p=1$" + "a" * 22 + "$" + "b" * 43


def raw(**overrides: object) -> str:
    base = {
        "command_id": str(uuid4()),
        "approver_email": "owner@example.test",
        "issue": "owner chat 30 Oct 2026",
        "owner_email": "owner@example.test",
        "admin_email": "coach@example.test",
        "seller_mailbox": "owner@example.test",
        "organisations": ["ac", "cyber"],
        "password_hashes": {"owner+ac.priya@example.test": VERIFIER},
    }
    return json.dumps({**base, **overrides})


def test_a_full_input_is_accepted_with_its_defaults() -> None:
    got = change.spec_of(raw())
    assert got["days"] == 30 and got["scale"] == 1.0 and got["end"] is None
    assert got["test_data"] is True and got["require_pipeline"] is True
    assert change.spec_of(raw(end="2026-10-30"))["end"] == date(2026, 10, 30)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"organisations": ["ac", "solar"]}, "unknown_organisation"),
        ({"organisations": ["ac", "ac"]}, "organisation_twice"),
        ({"seller_mailbox": "nobody"}, "seller_mailbox_not_an_email"),
        ({"days": 0}, "days_out_of_range"),
        ({"scale": 5}, "scale_out_of_range"),
        ({"password_hashes": {"a@example.test": "hunter2"}}, "password_hash_not_a_verifier"),
    ],
)
def test_a_wrong_input_is_refused(overrides: dict[str, object], reason: str) -> None:
    with pytest.raises(SystemExit) as refused:
        change.spec_of(raw(**overrides))
    assert json.loads(str(refused.value))["refused"] == reason


def test_a_missing_field_is_refused() -> None:
    body = json.loads(raw())
    del body["admin_email"]
    with pytest.raises(SystemExit) as refused:
        change.spec_of(json.dumps(body))
    assert json.loads(str(refused.value)) == {"refused": "missing_input", "fields": ["admin_email"]}


def test_each_seller_signs_in_with_a_plus_alias_of_the_owners_mailbox() -> None:
    found = change.logins(change.spec_of(raw(seller_mailbox="Owner+old@Example.test")))
    emails = [email for key in ("ac", "cyber") for email in found[key]]
    assert len(found["ac"]) == len(found["cyber"]) == 5
    assert len(set(emails)) == 10
    assert all(email.startswith("owner+") and email.endswith("@example.test") for email in emails)
    assert "owner+ac.priya@example.test" in found["ac"]


def test_the_two_organisations_are_fictional_teams_in_pune_and_mumbai() -> None:
    for org in change.ORGS.values():
        assert len(org.sellers) == 5
        assert {seller.city for seller in org.sellers} == {"Pune", "Mumbai"}
        assert len({(s.first, s.last) for s in org.sellers}) == 5
        labels = " ".join(source.label for source in org.sources)
        for word in ("Meta", "Website", "Google", "WhatsApp", "Justdial"):
            assert word in labels
        assert [s.label for s in org.sources if s.typed] == ["Justdial"]
        assert org.cold_label.startswith("File: ")
        assert org.meeting[2] is None or "example.com" in org.meeting[2]
        assert sum(1 for s in org.sellers if s.joins) == 1
    assert change.ORGS["ac"].name != change.ORGS["cyber"].name


def test_no_lead_number_can_ring_anyone() -> None:
    for org in change.ORGS.values():
        numbers = {change.fictional_phone(org, n) for n in range(1, 2000)}
        assert len(numbers) == 1999
        for number in numbers:
            stored = normalise_phone(number)
            # Stored as the app stores phones, but +91 then 0 is no Indian number.
            assert stored is not None and stored.startswith("+9100000")


def test_a_sellers_day_runs_from_half_past_ten_to_seven_with_lunch() -> None:
    star, *_, joiner = change.ORGS["ac"].sellers
    weak = change.ORGS["ac"].sellers[3]
    first = date(2026, 10, 1)
    gaps: Counter[str] = Counter()
    for offset in range(120):
        day = first + timedelta(days=offset)
        for who, seller in (("star", star), ("weak", weak)):
            shape = change.day_shape(change.rng_for(SEED, who, offset), seller, day, offset)
            if day.weekday() == 6:
                assert shape is None
            if shape is None:
                continue
            start, end = shape.start.astimezone(IST), shape.end.astimezone(IST)
            assert time(10, 30) <= start.time() < time(11, 30)
            assert time(18, 30) <= end.time() < time(19, 0)
            lunch = shape.lunch[1] - shape.lunch[0]
            assert timedelta(minutes=35) <= lunch <= timedelta(minutes=55)
            assert time(13, 15) <= shape.lunch[0].astimezone(IST).time() <= time(14, 0)
            for begin, finish in shape.gaps:
                assert timedelta(minutes=60) <= finish - begin <= timedelta(minutes=120)
                assert begin.astimezone(IST).time() >= time(11, 15) and finish < shape.end
            gaps[who] += bool(shape.gaps)
            windows = shape.windows
            assert windows[0][0] >= shape.start and windows[-1][1] <= shape.end
            assert all(a[1] <= b[0] for a, b in zip(windows, windows[1:], strict=False))
    # The weak seller disappears for an hour or two on many days; the star rarely does.
    assert gaps["weak"] > 3 * gaps["star"]
    assert change.day_shape(change.rng_for(SEED), joiner, date(2026, 10, 5), 3) is None


def test_enquiries_come_in_through_the_day_and_fewer_on_sunday() -> None:
    org = change.ORGS["cyber"]
    weekday = [
        len(change.arrivals(change.rng_for(SEED, n), org, date(2026, 10, 28), 1.0))
        for n in range(40)
    ]
    sunday = [
        len(change.arrivals(change.rng_for(SEED, n), org, date(2026, 10, 25), 1.0))
        for n in range(40)
    ]
    assert 0.75 * org.daily <= sum(weekday) / 40 <= 1.25 * org.daily
    assert sum(sunday) < sum(weekday)
    times = change.arrivals(change.rng_for(SEED), org, date(2026, 10, 28), 1.0)
    assert times == sorted(times)
    assert all(moment.astimezone(IST).date() == date(2026, 10, 28) for moment in times)


def test_talk_times_and_follow_ups_look_like_a_sales_desk() -> None:
    rng = change.rng_for(SEED)
    assert all(8 <= change.talk_seconds(rng, "junk", 1.0) <= 90 for _ in range(50))
    assert all(300 <= change.talk_seconds(rng, "meet", 1.0) <= 900 for _ in range(50))
    after = change.at(date(2026, 10, 30), time(18, 50))  # a Friday evening
    for _ in range(50):
        slot = change.next_slot(rng, after, days=(1, 3)).astimezone(IST)
        assert slot.weekday() in change.WORK_DAYS
        assert time(11, 0) <= slot.time() <= time(17, 30)
        assert slot > after


def test_the_plan_is_the_same_every_time() -> None:
    command = uuid4()
    first = [change.rng_for(command, "ac", "work").random() for _ in range(5)]
    again = [change.rng_for(command, "ac", "work").random() for _ in range(5)]
    assert first == again
    assert first != [change.rng_for(command, "cyber", "work").random() for _ in range(5)]


def test_each_login_is_kept_in_infisical_under_its_alias() -> None:
    assert logins_tool.secret_name("admin+ac.priya@authorityclosers.com") == (
        "SANDBOX_LOGIN_AC_PRIYA"
    )
    assert logins_tool.secret_name("Owner+cy.vikas@example.test") == "SANDBOX_LOGIN_CY_VIKAS"
    with pytest.raises(SystemExit):
        logins_tool.secret_name("owner@example.test")


def test_the_laptop_verifier_is_the_one_the_app_signs_in_with() -> None:
    made = logins_tool.verifier("fictional-sandbox-login-1")
    assert change.VERIFIER.match(made)
    assert verify_password("fictional-sandbox-login-1", made)
    assert not verify_password("another-password-entirely", made)
    assert change.spec_of(raw(password_hashes={"owner+ac.priya@example.test": made}))
