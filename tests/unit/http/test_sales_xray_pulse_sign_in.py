"""Sign in (and sign up) with Pulse on Sales Xray: offered only once configured, the
transaction bound to Pulse and its own callback, discovery read before the address is
made, a verified Pulse email links an existing account like Google, and the person's
Pulse name, title, team and photo address are kept for their profile."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import ac_platform.http.auth as auth_module
from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.rate_limits import DEFAULT_RATE_LIMIT_RULES
from ac_platform.identity.services import VerifiedProviderAssertion
from ac_platform.pulse.oidc import PulseClaims
from tests.unit.http.test_auth_routes import DEPLOYMENT_SESSION_COOKIE, _IdentityApplication
from tests.unit.http.test_sales_xray_auth import SALES_STAGING_HOST, SALES_STAGING_ORIGIN
from tests.unit.http.test_sales_xray_provider_sign_in import (
    _callback,
    _client,
    _Provider,
    _quiet_side_effects,  # noqa: F401 - the autouse fixture applies here too
    _result,
    _start,
    _transaction,
)

PULSE = "https://pulse.example.test"


class _Pulse(_Provider):
    """A Pulse double: discovery to prepare, then one verified person."""

    def __init__(self) -> None:
        super().__init__("pulse", email="kiran.mehta@example.test")
        self.issuer = PULSE
        self.prepared = 0
        self.kept: dict[str, PulseClaims] = {}

    async def prepare(self) -> None:
        self.prepared += 1

    def claims_for(self, state: str) -> PulseClaims | None:
        return self.kept.pop(state, None)

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        self.exchanges.append({"code": code, "redirect_uri": redirect_uri})
        self.kept[callback_state] = PulseClaims(
            issuer=PULSE,
            subject="pulse-person-1",
            name="Kiran Mehta",
            title="Sales manager",
            team="Inside sales",
            picture=f"{PULSE}/people/pulse-person-1/photo?v=3f9c",
        )
        return VerifiedProviderAssertion(
            issuer=PULSE,
            subject="pulse-person-1",
            audience=self.audience,
            state=callback_state,
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email=self.email,
            email_verified=True,
            display_name="Kiran Mehta",
        )


def test_pulse_is_offered_only_once_configured() -> None:
    def flag(client: Any) -> bool:
        body = client.get(
            "/v1/auth/email-code/config",
            params={"surface": "sales_xray"},
            headers={"host": SALES_STAGING_HOST},
        ).json()
        return bool(body["pulse_enabled"])

    assert flag(_client()) is False
    assert flag(_client(extra={"pulse": _Pulse()})) is True
    assert _start(_client(), "pulse").status_code == 503


def test_start_reads_discovery_and_binds_the_pulse_callback() -> None:
    pulse = _Pulse()
    response = _start(_client(extra={"pulse": pulse}), "pulse")
    assert response.status_code == 303
    assert pulse.prepared == 1
    location = parse_qs(urlsplit(response.headers["location"]).query)
    assert location["redirect_uri"] == [f"{SALES_STAGING_ORIGIN}/v1/auth/pulse/callback"]
    transaction, _ = _transaction(response)
    assert transaction.provider == "pulse"


def test_a_pulse_sign_in_links_by_verified_email_and_keeps_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[dict[str, Any]] = []

    async def record(_database: object, **values: Any) -> str | None:
        saved.append(values)
        return values["claims"].picture

    async def empty_profile(_database: object, *, person_id: object) -> Any:
        del person_id
        return type("Profile", (), {"name": None, "phone_number_e164": None, "revision": 0})()

    async def save_profile(_database: object, **values: Any) -> None:
        names.append(values["full_name"])

    names: list[str] = []
    monkeypatch.setattr(auth_module, "get_sales_xray_profile", empty_profile)
    monkeypatch.setattr(auth_module, "update_sales_xray_profile", save_profile)
    monkeypatch.setattr(auth_module, "record_pulse_profile", record)
    pulse = _Pulse()
    client = _client(extra={"pulse": pulse})
    transaction, encoded = _transaction(_start(client, "pulse"))
    callback = _callback(client, "pulse", transaction, encoded)
    assert _result(callback) == "success"
    assert callback.cookies[DEPLOYMENT_SESSION_COOKIE]
    [call] = _IdentityApplication.registered_provider_calls
    assert call["link_existing_email"] is True
    assert pulse.exchanges == [
        {"code": "provider-code", "redirect_uri": f"{SALES_STAGING_ORIGIN}/v1/auth/pulse/callback"}
    ]
    # Pulse's name fills an empty Sales Xray profile name, like Google's.
    assert names == ["Kiran Mehta"]
    [kept] = saved
    assert kept["source"] == "sign_in"
    assert (kept["claims"].title, kept["claims"].team) == ("Sales manager", "Inside sales")


def test_a_google_transaction_is_refused_at_the_pulse_callback() -> None:
    pulse = _Pulse()
    client = _client(extra={"pulse": pulse})
    transaction, encoded = _transaction(_start(client, "google"))
    assert _result(_callback(client, "pulse", transaction, encoded)) == "failed"
    assert pulse.exchanges == []


def test_pulse_routes_share_the_sign_in_rate_limits() -> None:
    by_name = {rule.name: rule for rule in DEFAULT_RATE_LIMIT_RULES}
    assert by_name["oauth-start"].path.fullmatch("/v1/auth/pulse/start")
    assert by_name["oauth-callback"].path.fullmatch("/v1/auth/pulse/callback")
    assert by_name["sign-in-method-connect"].path.fullmatch("/v1/me/sign-in-methods/pulse/connect")
