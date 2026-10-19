"""Developer platform rules without a database: key format, scopes and sealing."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.integrations import keys, scopes, sealed
from ac_platform.integrations.errors import IntegrationError

KEY = sealed.key_from(base64.urlsafe_b64encode(b"k" * 32).decode())


def test_keys_are_long_random_and_tied_to_their_environment_kind() -> None:
    live, test = keys.generate("production"), keys.generate("staging")
    assert live.startswith("sxk_live_") and test.startswith("sxk_test_")
    assert keys.KEY_PATTERN.fullmatch(live) and keys.KEY_PATTERN.fullmatch(test)
    assert len({keys.generate("staging") for _ in range(50)}) == 50
    assert len(keys.digest(live)) == 64 and keys.digest(live) != keys.digest(test)
    assert keys.mode("development") == "test" and keys.mode("production") == "live"


def test_scopes_are_known_sorted_and_never_empty() -> None:
    assert scopes.validate(["leads:read", "calls:read", "leads:read"]) == [
        "calls:read",
        "leads:read",
    ]
    for wrong in ([], ["calls:write"], [3]):
        with pytest.raises(scopes.ScopeError):
            scopes.validate(wrong)
    assert {item["key"] for item in scopes.public()} == set(scopes.SCOPES)


def test_a_sealed_secret_opens_only_for_its_own_row() -> None:
    assert KEY is not None and len(KEY.key_id) == 16
    secret_id, tenant_id = uuid4(), uuid4()
    blob = sealed.seal(
        KEY, secret_id=secret_id, tenant_id=tenant_id, purpose="webhook_signing", value=b"whsec_x"
    )
    assert b"whsec_x" not in blob.encode()
    row = SimpleNamespace(
        id=secret_id,
        tenant_id=tenant_id,
        purpose="webhook_signing",
        sealed=blob,
        seal_key_id=KEY.key_id,
    )
    assert sealed.unseal(KEY, row) == b"whsec_x"
    # Copied onto another row, another organisation or another purpose: it does not open.
    for change in ({"id": uuid4()}, {"tenant_id": uuid4()}, {"purpose": "partner_key"}):
        with pytest.raises(IntegrationError):
            sealed.unseal(KEY, SimpleNamespace(**{**row.__dict__, **change}))
    other = sealed.key_from(base64.urlsafe_b64encode(b"o" * 32).decode())
    assert other is not None
    with pytest.raises(IntegrationError, match="seal_key_mismatch"):
        sealed.unseal(other, row)


def test_platform_key_and_secret_names() -> None:
    assert sealed.key_from("short") is None and sealed.key_from("!!!") is None
    assert sealed.load_key({}) is None
    assert sealed.load_key({sealed.ENV: base64.urlsafe_b64encode(b"k" * 32).decode()}) == KEY
    secret_id = uuid4()
    ref = sealed.ref_for(secret_id)
    # It fits the partner webhook tables' secret_ref pattern (0096/0102).
    assert ref.startswith("AC_PARTNER_WEBHOOK_SECRET__") and len(ref) <= 91
    assert sealed.id_from_ref(ref) == secret_id
    assert sealed.id_from_ref("AC_PARTNER_WEBHOOK_SECRET__PARTNER") is None
    assert sealed.id_from_ref(None) is None
    made = sealed.new_webhook_secret()
    assert made.startswith("whsec_") and len(made) == 46
