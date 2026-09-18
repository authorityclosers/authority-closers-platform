"""Single fixed synthetic Gemini smoke, isolated from HTTP and offline workers.

Launch through scoped external secret injection. No recording-path parameter,
customer data, retry, subscription, credits purchase or unbounded generation.
The external private receipt preserves reservation-before-dispatch ordering.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    ExecutionPermission,
    MinuteAccount,
    MinuteGrant,
    Quote,
    Reservation,
    grant_minutes,
    mark_dispatched,
    mark_uncertain,
    reserve,
)
from ac_platform.conversation_intelligence.providers import BoundedProviders, ProviderError
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-receipt-directory", type=Path, required=True)
    parser.add_argument(
        "--model",
        choices=["gemini-2.5-flash", "gemini-3.8-flash", "openai/gpt-oss-120b", "scribe_v2"],
        default="gemini-3.8-flash",
    )
    args = parser.parse_args()
    root = PrivateLocalRecordingStorage(args.private_receipt_directory)
    journal = root.root / "inference-smoke.jsonl"
    # Exclusive receipt file makes rerunning this exact smoke an explicit new action.
    with journal.open("x", encoding="utf-8") as stream:
        body: dict[str, Any] = {
            "contents": [
                {"parts": [{"text": "Synthetic API connectivity test. Reply with READY only."}]}
            ],
            "generationConfig": {
                # The limit includes thinking: 16 tokens produced HTTP 200 with
                # no answer on Gemini 3.8. Keep a small, fixed total allowance.
                "maxOutputTokens": 256,
                "temperature": 0,
                "thinkingConfig": (
                    {"thinkingLevel": "LOW"}
                    if args.model == "gemini-3.8-flash"
                    else {"thinkingBudget": 0}
                ),
            },
        }
        provider_id = "groq" if args.model == "openai/gpt-oss-120b" else "gemini"
        audio = b""
        if args.model == "scribe_v2":
            provider_id = "elevenlabs"
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 16000)
            audio = buffer.getvalue()
        if provider_id == "groq":
            body = {
                "model": args.model,
                "messages": [
                    {"role": "user", "content": "This is a synthetic API test. Reply READY only."}
                ],
                "max_completion_tokens": 256,
                "reasoning_effort": "low",
                "temperature": 0,
            }
        digest = hashlib.sha256(audio if audio else canonical(body)).hexdigest()
        now = int(time.time())
        scope, tenant, account, recording, identifier = (str(uuid4()) for _ in range(5))
        quote = Quote(
            identifier,
            SourceBinding(tenant, recording, digest, "synthetic-1"),
            account,
            scope,
            provider_id,
            args.model,
            "synthetic-connectivity-v1",
            "transcribe_scribe_v2" if audio else "extract_context_evidence",
            digest,
            "public-synthetic-no-personal-data",
            "owner-request:test-provided-apis-20260913",
            {
                "groq": "https://console.groq.com/docs/your-data",
                "gemini": "https://ai.google.dev/gemini-api/terms",
                "elevenlabs": "https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode",
            }[provider_id],
            "synthetic-only-no-customer-data",
            "software-connectivity-test-only",
            "owner-supplied-free-tier-no-billing-activation",
            1 if audio else 0,
            0,
            now,
            now + 300,
        )
        permission = ExecutionPermission(
            "owner-request:test-provided-apis-20260913", quote.fingerprint, "owner", now + 300
        )
        approval = BudgetCapApproval(
            scope,
            "zero-paid-smoke-cap",
            "owner",
            0,
            "0" * 64,
            "No paid allocation for synthetic smoke",
        )
        minutes = MinuteAccount(tenant, account)
        if audio:
            minutes = grant_minutes(
                minutes,
                MinuteGrant(
                    tenant,
                    account,
                    str(uuid4()),
                    1,
                    "owner:synthetic-api-test",
                    "owner",
                    "One second of generated silence",
                ),
            )
        held = reserve(
            minutes,
            BudgetAccount(scope, 0, approval),
            identifier,
            quote,
            permission,
            now,
        )

        def write(event: dict[str, Any]) -> None:
            stream.write(json.dumps(event, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

        write(
            {
                "event": "reserved",
                "quote": quote.as_dict(),
                "minutes": held.minutes.as_dict(),
                "budget": held.budget.as_dict(),
            }
        )
        dispatched = mark_dispatched(held.minutes, held.budget, identifier, str(uuid4()), now)
        write({"event": "in_flight", "reservation": dispatched.reservation.as_dict()})

        def gate(current: Reservation) -> None:
            if current != dispatched.reservation or current.quote.input_sha256 != digest:
                raise ProviderError("smoke_dispatch_mismatch")

        credential = os.environ.pop(
            {
                "groq": "GROQ_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "elevenlabs": "ELEVENLABS_API_KEY",
            }[provider_id],
            "",
        )
        for key in ("ELEVENLABS_API_KEY", "GROQ_API_KEY", "SARVAM_API_KEY", "GEMINI_API_KEY"):
            os.environ.pop(key, None)
        provider = BoundedProviders(credentials={provider_id: credential}, authorize=gate)
        receipt = {
            "provider": provider_id,
            "model": quote.provider_model,
            "requests": 1,
            "synthetic_only": True,
            "customer_recording_bytes": 0,
            "max_paid_paise": 0,
            "credit_purchases": 0,
            "max_output_tokens": (None if audio else 256),
        }
        try:
            result = (
                provider.transcribe(dispatched.reservation, audio)
                if audio
                else provider.generate(dispatched.reservation, body)
            )
            candidates = result.data.get("candidates", [])
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            generated = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if provider_id == "groq":
                choices = result.data.get("choices", [])
                generated = choices[0].get("message", {}).get("content", "") if choices else ""
            if audio:
                generated = (
                    "READY"
                    if isinstance(result.data.get("text"), str)
                    and isinstance(result.data.get("words"), list)
                    else ""
                )
            receipt.update(
                http_status=200,
                generation_worked=generated.strip() == "READY",
                usage=result.usage,
                response_sha256=result.response_sha256,
            )
            if provider_id == "gemini":
                receipt["finish_reason"] = candidates[0].get("finishReason") if candidates else None
        except ProviderError as error:
            receipt.update(
                generation_worked=False, error_code=str(error), diagnostic=error.diagnostic
            )
        # Response token counts are not an invoice; preserve uncertainty rather
        # than manufacturing a zero-charge settlement from absent billing data.
        uncertain = mark_uncertain(
            dispatched.minutes, dispatched.budget, identifier, "smoke:awaiting-usage-reconciliation"
        )
        write(
            {
                "event": "response",
                "receipt": receipt,
                "reservation": uncertain.reservation.as_dict(),
            }
        )
        print(json.dumps(receipt, allow_nan=False))


if __name__ == "__main__":
    main()
