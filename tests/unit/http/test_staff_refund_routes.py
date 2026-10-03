"""Admin surface, fresh authority and request contract for AUT-889."""

import pytest

from tests.unit.http.test_billing_routes import _client, _Commands, _headers

PATH = "/v1/platform/billing/payments/fake_pay_1/refund"
ADMIN_ORIGIN = "https://admin.authorityclosers.test"
HEADERS = {"Host": "admin.authorityclosers.test", "Origin": ADMIN_ORIGIN, "Idempotency-Key": "r1"}


def test_staff_refund_uses_fresh_capability_and_preserves_the_response(monkeypatch):
    commands = _Commands()
    client, actor, _ = _client(commands, membership_role="owner")
    permissions = {"platform_billing_manage"}
    checks = []

    async def project(database, current_actor, *, operations_tenant_id):
        checks.append(current_actor)
        return frozenset(permissions)

    monkeypatch.setattr("ac_platform.http.billing.platform_projection", project)
    first = client.post(PATH, json={"reason": "Customer support request"}, headers=HEADERS)
    assert first.status_code == 202
    assert first.json() == {
        "refund": {
            "payment_id": "fake_pay_1",
            "refundable_until": "2026-10-08T09:00:00Z",
            "state": "pending",
            "reason_code": None,
        }
    }
    assert first.headers["cache-control"] == "private, no-store"
    name, call = commands.calls[0]
    assert name == "staff_refund_payment"
    assert call["caller"].person_id == actor.person_id
    assert call["reason"] == "Customer support request"
    assert call["key"] == "r1"
    commands.refund_state = "refunded"
    assert client.post(PATH, json={"reason": "x"}, headers=HEADERS).status_code == 200
    permissions.clear()
    denied = client.post(PATH, json={"reason": "x"}, headers=HEADERS)
    assert denied.status_code == 403
    assert len(checks) == 3
    assert len(commands.calls) == 2


@pytest.mark.parametrize(
    ("body", "headers", "expected_status"),
    [
        ({}, HEADERS, 422),
        ({"reason": ""}, HEADERS, 422),
        ({"reason": " \t"}, HEADERS, 422),
        ({"reason": "x" * 501}, HEADERS, 422),
        ({"reason": 12}, HEADERS, 422),
        ({"reason": "x", "amount": 1}, HEADERS, 422),
        ({"reason": "x"}, {"Host": "admin.authorityclosers.test", "Origin": ADMIN_ORIGIN}, 428),
    ],
)
def test_staff_refund_rejects_invalid_commands(monkeypatch, body, headers, expected_status):
    async def project(*args, **kwargs):
        return frozenset({"platform_billing_manage"})

    monkeypatch.setattr("ac_platform.http.billing.platform_projection", project)
    client, _, _ = _client(commands := _Commands())
    assert client.post(PATH, json=body, headers=headers).status_code == expected_status
    assert commands.calls == []


@pytest.mark.parametrize(
    "headers",
    [_headers(), HEADERS | {"Origin": "https://untrusted.example.test"}, {"Host": HEADERS["Host"]}],
)
def test_staff_refund_rejects_other_surfaces_and_unsafe_origins(headers):
    client, _, _ = _client(commands := _Commands())
    assert client.post(PATH, json={"reason": "x"}, headers=headers).status_code == 403
    assert commands.calls == []
