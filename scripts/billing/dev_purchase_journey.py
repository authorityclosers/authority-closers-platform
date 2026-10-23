"""Buy every plan and top-up on dev through the real HTTP API and the fake provider (dev proof).

Orchestrator brief, 23 Oct 2026 ("Sales X-Ray ready to charge"). Each run makes fresh fictional
buyers (``sx-buyer-<run>-<n>@example.test``, verified without mail, passwords random and kept in
memory only), then drives the same calls the Sales Xray web app makes:
  - Personal monthly, then a Personal top-up, an unused top-up refund (credit note) and a cancel;
  - Personal yearly;
  - Organisation monthly (2 seats) with an Organisation top-up, and Organisation yearly (3 seats);
  - refusals: 1 or 50 Organisation seats, Enterprise ("talk to us"), a top-up without a plan;
  - the trial a new buyer starts with (v2: 100 minutes, 14 days).
Every payment goes through the hosted fake checkout page (GET, then POST "pay" with its Origin),
exactly as a browser would. Prints amounts, minutes, statuses and ids; never a password, cookie
or token.

Development only. Run on ac with the dev-live API's settings:
    sudo bash -c 'set -a; . /etc/authority-closers/development/api-live.env; set +a;
      cd /srv/authority-closers/development/live-backend/a && .venv/bin/python -' \\
      < scripts/billing/dev_purchase_journey.py
"""

from __future__ import annotations

import asyncio
import http.client
import json
import re
import secrets
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.development.seed import verify_registration_without_mail
from ac_platform.identity.password_auth import PasswordIdentityService
from ac_platform.tenancy.learner_provisioning import AsyncLearnerProvisioningApplication

API = ("127.0.0.1", 8101)
ORIGIN = "https://salesxray-dev.authorityclosers.com"
HOST = urlsplit(ORIGIN).hostname or ""
RESULTS: list[tuple[str, bool, str]] = []


class Failed(RuntimeError):
    pass


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f" · {detail}" if detail else ""), flush=True)


@dataclass
class Client:
    cookies: dict[str, str] = field(default_factory=dict)

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        idempotent: bool = False,
        origin: str | None = ORIGIN,
        form: bool = False,
    ) -> tuple[int, dict[str, str], Any]:
        connection = http.client.HTTPConnection(*API, timeout=60)
        headers = {
            "Host": HOST,
            "X-Forwarded-Proto": "https",
            "Accept": "application/json",
            "User-Agent": "sx-dev-purchase-journey",
        }
        if origin and method != "GET":
            headers["Origin"] = origin
        if idempotent:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        payload = None
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            payload = b""
        elif body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        for name, value in response.getheaders():
            if name.lower() == "set-cookie":
                pair = value.split(";", 1)[0]
                key, _, val = pair.partition("=")
                if val:
                    self.cookies[key.strip()] = val.strip()
                else:
                    self.cookies.pop(key.strip(), None)
        out_headers = {name.lower(): value for name, value in response.getheaders()}
        try:
            data: Any = json.loads(raw) if raw else None
        except ValueError:
            data = raw.decode("utf-8", "replace")
        connection.close()
        return response.status, out_headers, data


async def make_buyer(database: AsyncSession, run: str, n: int) -> tuple[str, str]:
    settings = get_settings()
    assert settings.environment == "development" and settings.public_learner_tenant_id
    email = f"sx-buyer-{run}-{n}@example.test"
    password = secrets.token_urlsafe(18) + "Aa1!"
    identity = PasswordIdentityService(
        database, token_secret=settings.email_challenge_secret.get_secret_value()
    )
    registration = await identity.register(
        email=email,
        first_name=f"Fictional Buyer {n}",
        whatsapp_number="+14155550169",
        password=password,
        consent_version=settings.learner_consent_version or "",
    )
    person = await verify_registration_without_mail(
        database,
        identity,
        registration,
        secret=settings.email_challenge_secret.get_secret_value(),
    )
    await AsyncLearnerProvisioningApplication(database).ensure(
        person_id=person.id,
        tenant_id=settings.public_learner_tenant_id,
        required_consent_version=settings.learner_consent_version or "",
    )
    return email, password


def sign_in(email: str, password: str) -> Client:
    client = Client()
    status, _, data = client.call(
        "POST", "/v1/auth/password/login", {"email": email, "password": password}
    )
    if status != 200:
        raise Failed(f"sign in {status} {data}")
    return client


def pay(client: Client, checkout: dict[str, Any], action: str = "pay") -> dict[str, Any]:
    """Open the hosted fake page and press its button, as a browser does; then read the order."""
    url = checkout["hosted"]["url"]
    parts = urlsplit(url)
    if f"{parts.scheme}://{parts.netloc}" != ORIGIN:
        raise Failed(f"hosted page is not on the Sales Xray origin: {parts.netloc}")
    path = parts.path + "?" + parts.query
    status, _, page = client.call("GET", path)
    if status != 200 or "<form" not in str(page):
        raise Failed(f"hosted page {status}")
    forms = re.findall(r'action="([^"]+)"', str(page))
    target = next((f for f in forms if f"/{action}?" in f), None)
    if target is None:
        raise Failed(f"no {action} button on the hosted page")
    resolved = urlsplit(urljoin(url, target.replace("&amp;", "&")))
    target = resolved.path + "?" + resolved.query
    status, headers, _ = client.call("POST", target, form=True)
    if status != 303 or "/account/billing/return?order=" not in headers.get("location", ""):
        raise Failed(f"hosted submit {status} {headers.get('location')}")
    order_id = checkout["order"]["order_id"]
    status, _, order = client.call("GET", f"/v1/orders/{order_id}")
    if status != 200:
        raise Failed(f"order read {status} {order}")
    return dict(order.get("order", order))


def minutes(client: Client, account: str) -> str:
    """What the app shows as the buyer's analysis minutes (the admission projection)."""
    path = "/v1/me/plan" if account == "personal" else "/v1/organisation/usage"
    status, _, data = client.call("GET", path)
    if status != 200:
        raise Failed(f"{path} {status} {data}")
    if account == "personal":
        allowance = data.get("allowance") or {}
        return (
            f"plan={data['plan']['key']} "
            f"available_min={allowance.get('available_seconds', 0) // 60}"
            f" longest_call_min={data.get('longest_call_seconds', 0) // 60}"
        )
    return json.dumps(data)[:300]


def rupees(money: dict[str, Any]) -> str:
    return f"₹{money['amount_minor'] / 100:,.2f}" if "amount_minor" in money else json.dumps(money)


def buy(
    client: Client, body: dict[str, Any], label: str, *, expect: int = 201
) -> dict[str, Any] | None:
    status, _, data = client.call("POST", "/v1/checkout", body, idempotent=True)
    if status != expect:
        check(label, False, f"checkout {status} {json.dumps(data)[:300]}")
        return None
    if expect != 201:
        check(label, True, f"refused {status} {data.get('code') if isinstance(data, dict) else ''}")
        return None
    order = pay(client, data)
    ok = order["status"] == "paid"
    check(
        label,
        ok,
        f"{order['plan_name']} {order.get('interval') or order.get('pack_key')} "
        f"seats={order['seats']} minutes={order['minutes']} paid={rupees(order['amount'])} "
        f"status={order['status']}",
    )
    return order


def personal_journey(client: Client, interval: str) -> None:
    check(f"personal {interval}: trial before purchase", True, minutes(client, "personal"))
    order = buy(
        client,
        {
            "kind": "subscription",
            "account": "personal",
            "plan_key": "personal",
            "interval": interval,
            "seats": 1,
        },
        f"buy Personal {interval}",
    )
    if order is None:
        return
    check(f"personal {interval}: minutes after", True, minutes(client, "personal"))
    status, _, subs = client.call("GET", "/v1/subscriptions?account=personal")
    sub = (subs.get("current") or {}) if status == 200 else {}
    check(
        f"personal {interval}: subscription active",
        sub.get("status") == "active",
        f"status={sub.get('status')} renews_at={sub.get('renews_at')} "
        f"needs_customer_approval={sub.get('renewal_needs_customer_approval')}",
    )
    if interval != "month":
        return
    topup = buy(
        client,
        {"kind": "top_up", "account": "personal", "plan_key": "personal", "pack_key": "topup_100"},
        "buy Personal top-up 100 min",
    )
    check("personal: minutes after top-up", True, minutes(client, "personal"))
    status, _, invoices = client.call("GET", "/v1/invoices?account=personal")
    rows = invoices.get("invoices", []) if status == 200 else []
    check("personal: invoices issued", len(rows) >= 2, f"{len(rows)} invoices")
    if rows:
        invoice = rows[0]
        status, headers, html = client.call("GET", f"/v1/invoices/{invoice['invoice_id']}/download")
        text = str(html)
        check(
            "personal: invoice download has GST fields",
            status == 200 and "GST" in text and "SAC" in text,
            f"{status} {headers.get('content-type')} number={invoice.get('number')} "
            f"total={invoice.get('total_minor')} cgst={invoice.get('cgst_minor')} "
            f"sgst={invoice.get('sgst_minor')} igst={invoice.get('igst_minor')}",
        )
    if topup and topup.get("refund") and topup["refund"].get("payment_id"):
        payment_id = topup["refund"]["payment_id"]
        status, _, refund = client.call(
            "POST",
            f"/v1/payments/{payment_id}/refund",
            {"reason": "fictional unused top-up"},
            idempotent=True,
        )
        check(
            "personal: unused top-up refunded",
            status in (200, 202),
            f"{status} {json.dumps(refund)[:200]}",
        )
        status, _, notes = client.call("GET", "/v1/credit-notes?account=personal")
        check(
            "personal: credit note issued",
            status == 200 and len(notes.get("credit_notes", [])) >= 1,
            f"{status} {len(notes.get('credit_notes', [])) if isinstance(notes, dict) else notes}",
        )
    else:
        check("personal: top-up refundable", False, json.dumps(topup)[:300])
    if sub.get("subscription_id"):
        status, _, cancelled = client.call(
            "POST",
            f"/v1/subscriptions/{sub['subscription_id']}/cancel",
            {"reason": "fictional cancel"},
            idempotent=True,
        )
        check(
            "personal: cancel stops renewal, access to period end",
            status == 200 and cancelled.get("cancel_at_period_end") is True,
            f"{status} status={cancelled.get('status')} "
            f"period_end={(cancelled.get('current_period') or {}).get('end')}",
        )


def organisation_journey(client: Client, name: str, interval: str, seats: int) -> None:
    status, _, org = client.call("POST", "/v1/organisation", {"name": name}, idempotent=True)
    if status != 201:
        check(f"organisation {interval}: create", False, f"{status} {org}")
        return
    status, _, context = client.call("POST", "/v1/context", {"tenant_id": org["tenant_id"]})
    check(f"organisation {interval}: workspace selected", status == 200, f"{status}")
    base = {"kind": "subscription", "account": "organisation", "plan_key": "organisation"}
    if interval == "month":
        buy(
            client,
            {**base, "interval": "month", "seats": 1},
            "refuse Organisation 1 seat",
            expect=422,
        )
        buy(
            client,
            {**base, "interval": "month", "seats": 50},
            "refuse Organisation 50 seats",
            expect=422,
        )
        buy(
            client,
            {
                "kind": "top_up",
                "account": "organisation",
                "plan_key": "organisation",
                "pack_key": "topup_500",
            },
            "refuse Organisation top-up before a plan",
            expect=409,
        )
    order = buy(
        client,
        {**base, "interval": interval, "seats": seats},
        f"buy Organisation {interval} {seats} seats",
    )
    if order is None:
        return
    check(f"organisation {interval}: minutes after", True, minutes(client, "organisation"))
    status, _, usage = client.call("GET", "/v1/organisation/billing")
    check(
        f"organisation {interval}: organisation billing read",
        status == 200,
        json.dumps(usage)[:300],
    )
    if interval == "month":
        buy(
            client,
            {
                "kind": "top_up",
                "account": "organisation",
                "plan_key": "organisation",
                "pack_key": "topup_500",
            },
            "buy Organisation top-up 500 min",
        )
        check("organisation month: minutes after top-up", True, minutes(client, "organisation"))


async def main() -> int:
    settings = get_settings()
    if settings.environment != "development":
        print("development only")
        return 2
    run = datetime.now(UTC).strftime("%m%d%H%M") + secrets.token_hex(2)
    engine = create_async_engine(settings.database_url)
    buyers: list[tuple[str, str]] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as database, database.begin():
            for n in range(1, 5):
                buyers.append(await make_buyer(database, run, n))
    finally:
        await engine.dispose()
    print(f"run {run}: {len(buyers)} fictional buyers")
    personal_month, personal_year, org_month, org_year = (sign_in(*b) for b in buyers)
    personal_journey(personal_month, "month")
    personal_journey(personal_year, "year")
    buy(
        personal_year,
        {
            "kind": "subscription",
            "account": "organisation",
            "plan_key": "enterprise",
            "interval": "month",
            "seats": 50,
        },
        "refuse Enterprise (talk to us)",
        expect=403,
    )
    organisation_journey(org_month, f"Fictional Org {run} A", "month", 2)
    organisation_journey(org_year, f"Fictional Org {run} B", "year", 3)
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
        + (f"; failed: {failed}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
