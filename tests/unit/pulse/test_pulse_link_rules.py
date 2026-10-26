"""The Pulse org link's pure rules: webhook signatures, the member record, what is shared,
and which photo addresses Sales X-Ray will fetch. Fictional values only."""

from __future__ import annotations

import hashlib
import hmac
import time

from ac_platform.pulse.org_link import (
    EVENTS,
    MemberRecord,
    sharing_of,
    verify_signature,
)
from ac_platform.pulse.profile import photo_url_allowed

SECRET = "whsec_fictional0000000000000000000000000000"  # noqa: S105 - a test value


def _sign(body: bytes, stamp: int, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256)
    return f"t={stamp},v1={digest.hexdigest()}"


def test_a_signed_notice_is_accepted_only_fresh_and_unaltered() -> None:
    body = b'{"event_id":"e1","type":"person.updated","org_id":"o1","sub":"p1"}'
    now = int(time.time())
    assert verify_signature(_sign(body, now), body, SECRET, now=now)
    # Pulse rotating its secret may send two signatures.
    both = _sign(body, now, "whsec_old") + "," + _sign(body, now).split(",")[1]
    assert verify_signature(both, body, SECRET, now=now)
    assert not verify_signature(_sign(body, now), body + b" ", SECRET, now=now)
    assert not verify_signature(_sign(body, now, "whsec_other"), body, SECRET, now=now)
    assert not verify_signature(_sign(body, now - 301), body, SECRET, now=now)
    for wrong in (None, "", "v1=abc", "t=x,v1=abc", "t=1"):
        assert not verify_signature(wrong, body, SECRET, now=now)


def test_the_member_record_takes_only_what_the_contract_names() -> None:
    record = MemberRecord.parse(
        {
            "sub": "pulse-person-2",
            "email": "tara.kapoor@example.test",
            "email_verified": True,
            "name": "Tara Kapoor",
            "title": "Admin",
            "team": "Operations",
            "picture": "https://pulse.example.test/people/pulse-person-2/photo?v=1",
            "role": "admin",
            "status": "active",
            "updated_at": "2026-10-25T12:00:00Z",
            "salary": 1,
        }
    )
    assert record is not None
    assert (record.subject, record.email, record.email_verified) == (
        "pulse-person-2",
        "tara.kapoor@example.test",
        True,
    )
    assert record.updated_at is not None and record.updated_at.year == 2026
    assert MemberRecord.parse({"email": "no-sub@example.test"}) is None
    assert MemberRecord.parse("junk") is None
    unverified = MemberRecord.parse({"sub": "p3", "email": "x@example.test"})
    assert unverified is not None and unverified.email_verified is False
    assert unverified.status == "active"


def test_sharing_keeps_the_directory_and_defaults_signals_off() -> None:
    assert sharing_of(None) == {"directory": "read", "photos": "read", "signals": "off"}
    assert sharing_of({"photos": "off", "signals": "write", "directory": "write"}) == {
        "directory": "read",
        "photos": "off",
        "signals": "write",
    }
    assert sharing_of({"photos": "everything"})["photos"] == "read"


def test_photos_come_only_from_the_pulse_host() -> None:
    issuer = "https://pulse.example.test"
    assert photo_url_allowed(f"{issuer}/people/p1/photo?v=1", issuer)
    assert photo_url_allowed("https://cdn.pulse.example.test/p1.jpg", issuer)
    for wrong in (
        "https://evil.example.test/p1.jpg",
        "https://pulse.example.test.evil.test/p1.jpg",
        "http://pulse.example.test/p1.jpg",
        "https://user:pw@pulse.example.test/p1.jpg",
        "file:///etc/passwd",
        "",
        None,
    ):
        assert not photo_url_allowed(wrong, issuer), wrong


def test_the_webhook_events_are_the_contracts() -> None:
    assert set(EVENTS) == {
        "person.updated",
        "person.photo_updated",
        "membership.added",
        "membership.removed",
        "membership.role_changed",
        "link.revoked",
    }
