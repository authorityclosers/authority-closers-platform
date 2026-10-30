"""ac-cost-detect (30 Oct 2026): new costs found in email, proposed with a category and split,
filed in AC Pulse once each. Fictional messages and a fake Gmail; nothing leaves the test."""

from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/metrics/ac-cost-detect"


def runner():
    loader = importlib.machinery.SourceFileLoader("ac_cost_detect", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ac_cost_detect", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _part(mime: str, text: str) -> dict[str, Any]:
    data = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    return {"mimeType": mime, "body": {"data": data}}


def _message(message_id: str, sender: str, subject: str, *parts: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message_id,
        "snippet": "",
        "internalDate": "1793232000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Tue, 28 Oct 2026 09:00:00 +0000"},
            ],
            "parts": list(parts),
        },
    }


def test_amounts_prefer_the_total_and_rupees() -> None:
    job = runner()
    text = "Plan ₹17,236.56 GST ₹3,101.58 Total paid ₹20,338.14 thanks"
    assert job.pick(job.amounts(text)) == ("INR", 20338.14)
    assert job.pick(job.amounts("Credits US$21.10, fee $0.40")) == ("USD", 21.10)
    assert job.pick(job.amounts("Amount due: Rs. 1,000")) == ("INR", 1000.0)
    assert job.pick(job.amounts("No money here")) is None


def test_a_receipt_becomes_a_proposal_and_a_task() -> None:
    job = runner()
    receipt = _message(
        "m1",
        "Anthropic <invoice+statements@mail.anthropic.com>",
        "Your receipt from Anthropic",
        _part("text/plain", "Claude Max. Total ₹20,338.14 paid on 28 Oct."),
    )
    proposal = job.propose("admin@example.test", receipt)
    assert proposal is not None
    assert proposal["vendor"] == "Anthropic" and proposal["rupees"] == 20338.14
    assert proposal["category"] == "ai_subscriptions" and proposal["centre"] == "agents"
    assert proposal["split"] == {"rule": "token_burn", "tool": "claude"}
    assert proposal["confidence"] == "high" and proposal["date"] == "2026-10-28"
    op = job.task(proposal)
    assert op["op"] == "ensure" and op["marker"].startswith("cost:")
    assert op["fields"]["title"] == "Cost found: Anthropic ₹20,338.14 (2026-10-28)"
    assert f"Marker: {op['marker']}" in op["fields"]["notes"]
    # The task never carries the email's body.
    assert "Claude Max. Total" not in json.dumps(op, ensure_ascii=False)
    assert op["parent"]["title"] == job.PARENT


def test_dollars_html_google_kinds_and_unknown_senders() -> None:
    job = runner()
    credits = _message(
        "m2",
        "OpenRouter <receipts@openrouter.ai>",
        "Receipt",
        _part("text/html", "<p>Amount paid</p><b>$21.10</b><style>.x{}</style>"),
    )
    proposal = job.propose("admin@example.test", credits)
    assert proposal["currency"] == "USD" and proposal["rupees"] == pytest.approx(21.10 * 88)
    assert proposal["converted"] and proposal["cadence"] == "usage"
    assert "about ₹1,856.80" in job.task(proposal)["fields"]["title"]
    play = _message(
        "m3",
        "Google Payments <payments-noreply@google.com>",
        "Your Google Play Developer registration receipt",
        _part("text/plain", "Total: US$25.00"),
    )
    assert job.propose("admin@example.test", play)["category"] == "store_fees"
    shop = _message(
        "m4",
        "Orders <orders@unknownshop.example>",
        "Order placed",
        _part("text/plain", "Total ₹999"),
    )
    found = job.propose("admin@example.test", shop)
    assert found["vendor"] == "Unknownshop" and found["confidence"] == "low"
    free = _message(
        "m5",
        "Cloudflare <noreply@notify.cloudflare.com>",
        "Invoice",
        _part("text/plain", "Total $0.00"),
    )
    assert job.propose("admin@example.test", free) is None


class FakeGmail:
    def __init__(self, messages: dict[str, dict[str, Any]]) -> None:
        self.messages = messages

    def search(self, days: int) -> list[str]:
        assert days == 3
        return list(self.messages)

    def message(self, message_id: str) -> dict[str, Any]:
        return self.messages[message_id]


def test_each_message_is_filed_once() -> None:
    job = runner()
    inbox = {
        "m1": _message(
            "m1", "billing@elevenlabs.io", "Receipt", _part("text/plain", "Total ₹1,936.00")
        ),
        "m2": _message("m2", "news@elevenlabs.io", "Our news", _part("text/plain", "Hello")),
    }
    filed: list[dict[str, Any]] = []
    proposals, seen = job.run(
        ["admin@example.test"], lambda _mailbox: FakeGmail(inbox), filed.append, [], days=3
    )
    assert [item["vendor"] for item in proposals] == ["ElevenLabs"] and len(filed) == 1
    # Both messages are remembered (the newsletter is never read again), and the charge.
    assert len(seen) == 3
    again, seen_again = job.run(
        ["admin@example.test"], lambda _mailbox: FakeGmail(inbox), filed.append, seen, days=3
    )
    assert again == [] and len(filed) == 1 and seen_again == seen


def test_the_token_request_is_a_signed_read_only_assertion() -> None:
    job = runner()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    key = {"client_email": "reader@fictional.iam.example", "private_key": pem}
    token = job.assertion(key, "admin@example.test", 1_793_232_000)
    header, claims, signature = token.split(".")

    def decode(part: str) -> bytes:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

    body = json.loads(decode(claims))
    assert body["scope"] == "https://www.googleapis.com/auth/gmail.readonly"
    assert body["sub"] == "admin@example.test" and body["exp"] - body["iat"] == 3600
    private.public_key().verify(
        decode(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_without_a_key_nothing_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = runner()
    monkeypatch.setattr(job, "KEY", tmp_path / "missing.json")
    assert job.main([]) == 0


def test_notices_that_are_not_charges_are_skipped_and_a_charge_is_filed_once() -> None:
    # The first real run (30 Oct 2026) proposed these beside the one real receipt.
    job = runner()
    for sender, subject in (
        ("AWS <no-reply@signup.aws>", "Welcome to AWS - Your Account with Free Plan is Ready"),
        ("Anthropic <invoice@mail.anthropic.com>", "Credit note from Anthropic, PBC for invoice"),
        ("Google Cloud <billing-noreply@google.com>", "100% of budget reached"),
        ("Anthropic <billing@mail.anthropic.com>", "Action required: payment failed"),
    ):
        notice = _message("n", sender, subject, _part("text/plain", "Total ₹20,338.14"))
        assert job.propose("admin@example.test", notice) is None, subject
    inbox = {
        "r1": _message(
            "r1",
            "Anthropic <invoice@mail.anthropic.com>",
            "Your receipt from Anthropic",
            _part("text/plain", "Total ₹20,338.14"),
        ),
        "r2": _message(
            "r2",
            "Anthropic <invoice@mail.anthropic.com>",
            "Your invoice from Anthropic",
            _part("text/plain", "Amount paid ₹20,338.14"),
        ),
    }
    filed: list[dict[str, Any]] = []
    proposals, seen = job.run(
        ["admin@example.test"], lambda _mailbox: FakeGmail(inbox), filed.append, [], days=3
    )
    assert len(proposals) == 1 and len(filed) == 1
    assert len(seen) == 3  # two messages and the one charge


def test_threads_notifications_and_processor_receipts() -> None:
    # Real subjects from the 60-day look at admin@ (30 Oct 2026); numbers are fictional.
    job = runner()
    for sender, subject in (
        (
            "GitHub <notifications@github.com>",
            "Re: [org/repo] Add the offline corpus route (PR #4)",
        ),
        ("GitHub <notifications@github.com>", "[org/repo] Add the offline corpus route (PR #4)"),
        ("ChatGPT <noreply@tm.openai.com>", "[Task Update] Hourly operations watch"),
        ("OpenAI <noreply@tm.openai.com>", "Updates to your Pro plan"),
        ("Google <payments-noreply@google.com>", "Congrats! Your account has been upgraded"),
        ("Someone <a@example.test>", "Re: Re: Urgent: apply the annual credit"),
    ):
        mail = _message("n", sender, subject, _part("text/plain", "Total ₹1,000"))
        assert job.propose("admin@example.test", mail) is None, subject
    via_stripe = _message(
        "s1",
        "Eleven Labs Inc. <invoice+statements@stripe.com>",
        "Your receipt from Eleven Labs Inc. #2274-0126-4953",
        _part("text/plain", "Amount paid ₹1,936.00"),
    )
    proposal = job.propose("admin@example.test", via_stripe)
    assert proposal["vendor"] == "ElevenLabs" and proposal["category"] == "ai_product"
    assert proposal["confidence"] == "high"
    unknown = _message(
        "s2",
        "Shop <receipts@stripe.com>",
        "Your receipt from Fictional Tools Ltd #1",
        _part("text/plain", "Total ₹500"),
    )
    other = job.propose("admin@example.test", unknown)
    assert other["vendor"] == "Fictional Tools" and other["confidence"] == "low"


def test_our_own_mail_is_no_charge_but_a_forwarded_invoice_is() -> None:
    job = runner()
    ours = _message(
        "o1",
        "Owner <admin@example.test>",
        "Urgent: apply the annual credit to the new plan, invoice 0001",
        _part("text/plain", "Total ₹20,338.14"),
    )
    assert job.propose("admin@example.test", ours) is None
    forwarded = _message(
        "o2",
        "Teammate <dipak@example.test>",
        "Fwd: Your receipt from Anthropic",
        _part("text/plain", "Total ₹20,338.14"),
    )
    assert job.propose("admin@example.test", forwarded)["rupees"] == 20338.14
