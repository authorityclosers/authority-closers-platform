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

from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage
from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_generation_json_schema,
    coaching_response_json_schema,
)
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


def structured_probe_body(*, shape_only: bool = False) -> dict[str, Any]:
    """Fixed fictional request: test schema acceptance, not report quality."""
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Synthetic schema connectivity test only. "
                            "Fictional seller offers a booking "
                            "tool. Fictional buyer declines. No payment or follow-up was agreed. "
                            "Produce a brief draft report using the supplied schema."
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "candidateCount": 1,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
            "responseJsonSchema": (
                coaching_generation_json_schema() if shape_only else coaching_response_json_schema()
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-receipt-directory", type=Path, required=True)
    parser.add_argument(
        "--model",
        choices=["gemini-2.5-flash", "gemini-3.8-flash", "openai/gpt-oss-120b", "scribe_v2"],
        default="gemini-3.8-flash",
    )
    parser.add_argument("--structured-coaching-probe", action="store_true")
    parser.add_argument("--shape-only", action="store_true")
    parser.add_argument("--paid-approval-ref")
    args = parser.parse_args()
    if args.shape_only and not args.structured_coaching_probe:
        parser.error("Shape-only applies only to the fixed structured probe.")
    if args.structured_coaching_probe and (
        args.model != "gemini-3.8-flash"
        or args.paid_approval_ref != "ref:approval/owner-recovery-testing-inr1000-20260922"
    ):
        parser.error("Structured probe requires the exact owner recovery test approval and Flash.")
    if args.paid_approval_ref and not args.structured_coaching_probe:
        parser.error("Paid approval is supported only for the fixed structured probe.")
    maximum_cost = 100 if args.structured_coaching_probe else 0
    if args.structured_coaching_probe:
        estimated = estimate_provider_usage(
            "gemini",
            "gemini-3.8-flash",
            {
                "promptTokenCount": len(
                    canonical(structured_probe_body(shape_only=args.shape_only))
                )
                + 128,
                "candidatesTokenCount": 256,
            },
        )["paise"]
        if type(estimated) is not int or estimated > maximum_cost:
            parser.error("Fixed schema probe exceeds its one-rupee conservative ceiling.")
    approval_ref = args.paid_approval_ref or "owner-request:test-provided-apis-20260913"
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
        if args.structured_coaching_probe:
            body = structured_probe_body(shape_only=args.shape_only)
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
            approval_ref,
            {
                "groq": "https://console.groq.com/docs/your-data",
                "gemini": "https://ai.google.dev/gemini-api/terms",
                "elevenlabs": "https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode",
            }[provider_id],
            "synthetic-only-no-customer-data",
            "software-connectivity-test-only",
            (
                "fixed-synthetic-schema-probe-inr1-cap"
                if maximum_cost
                else "owner-supplied-free-tier-no-billing-activation"
            ),
            1 if audio else 0,
            maximum_cost,
            now,
            now + 300,
        )
        permission = ExecutionPermission(approval_ref, quote.fingerprint, "owner", now + 300)
        approval = BudgetCapApproval(
            scope,
            approval_ref if maximum_cost else "zero-paid-smoke-cap",
            "owner",
            maximum_cost,
            "0" * 64,
            "Fixed one-rupee schema probe"
            if maximum_cost
            else "No paid allocation for synthetic smoke",
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
            BudgetAccount(scope, maximum_cost, approval),
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
            "max_paid_paise": maximum_cost,
            "credit_purchases": 0,
            "max_output_tokens": (None if audio else 256),
        }
        if args.structured_coaching_probe:
            receipt.update(
                schema_probe=True,
                schema_sha256=hashlib.sha256(
                    canonical(body["generationConfig"]["responseJsonSchema"])
                ).hexdigest(),
                report_quality_test=False,
                owner_total_test_ceiling_paise=100_000,
            )
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
            if args.structured_coaching_probe:
                receipt["schema_accepted"] = True
            if provider_id == "gemini":
                receipt["finish_reason"] = candidates[0].get("finishReason") if candidates else None
        except ProviderError as error:
            receipt.update(
                generation_worked=False,
                error_code=str(error),
                diagnostic=error.diagnostic,
                diagnostic_markers=error.diagnostic_markers,
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
