"""Bounded private proof runner for an explicitly approved recording/provider test.

This CLI is not a hosted worker or HTTP surface. The supervising process enforces
a hard deadline; the child journals reservation-before-dispatch and never retries.
Keys are injected externally, removed from environment, and never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    ExecutionPermission,
    MinuteAccount,
    MinuteGrant,
    Quote,
    grant_minutes,
    mark_dispatched,
    mark_uncertain,
    reserve,
)
from ac_platform.conversation_intelligence.providers import (
    BoundedProviders,
    ProviderError,
    scribe_transcript,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage

VARIABLES = ("ELEVENLABS_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "SARVAM_API_KEY")


def write_private(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def execute(root: Path, stage: str) -> dict[str, Any]:
    store = PrivateLocalRecordingStorage(root)
    approval = json.loads((store.root / "approval.json").read_text(encoding="utf-8"))
    if (
        approval.get("approved") is not True
        or approval.get("max_paid_paise") != 0
        or approval.get("expires_at_epoch", 0) <= time.time()
        or approval.get("providers") != ["elevenlabs:scribe_v2", "groq:openai/gpt-oss-120b"]
    ):
        raise ProviderError("exact_test_approval_required")
    source = SourceBinding(**approval["source"])
    recording = Path(approval["source_path"])
    if (
        not recording.is_file()
        or recording.is_symlink()
        or recording.stat().st_size != approval["source_bytes"]
    ):
        raise ProviderError("approved_source_mismatch")
    data = recording.read_bytes()
    if hashlib.sha256(data).hexdigest() != source.source_sha256:
        raise ProviderError("approved_source_mismatch")
    provider = "elevenlabs" if stage == "transcript" else "groq"
    body = None
    if stage != "transcript":
        for previous in store.root.glob("report-*-journal.jsonl"):
            first = json.loads(previous.read_text(encoding="utf-8").splitlines()[0])
            if time.time() - first["quote"]["created_at_epoch"] < 65:
                raise ProviderError("free_tier_wait_for_next_token_window")
        request_file = store.root / f"{stage}-request.json"
        if not request_file.is_file() or request_file.stat().st_size > 128 * 1024:
            raise ProviderError("approved_report_request_required")
        body = json.loads(request_file.read_text(encoding="utf-8"))
        data = canonical(body)
    model = "scribe_v2" if provider == "elevenlabs" else "openai/gpt-oss-120b"
    digest = hashlib.sha256(data).hexdigest()
    now = int(time.time())
    quote = Quote(
        approval["test_id"] + ":" + stage,
        source,
        "owner-approved-test",
        approval["test_id"],
        provider,
        model,
        "owner-approved-private-proof-v1",
        "transcribe_scribe_v2" if stage == "transcript" else "extract_context_evidence",
        digest,
        approval["privacy_revision"],
        approval["authorization_ref"],
        approval["terms"][provider],
        approval["retention"][provider],
        "internal-draft-no-professional-or-official-score",
        approval["allowance_ref"],
        (approval["duration_ms"] + 999) // 1000 if stage == "transcript" else 0,
        0,
        now,
        min(now + 300, approval["expires_at_epoch"]),
    )
    minutes = MinuteAccount(source.tenant_id, "owner-approved-test")
    if quote.entitlement_seconds:
        minutes = grant_minutes(
            minutes,
            MinuteGrant(
                source.tenant_id,
                "owner-approved-test",
                quote.quote_id,
                quote.entitlement_seconds,
                approval["authorization_ref"],
                "owner",
                "Exact approved single recording test",
            ),
        )
    cap = BudgetCapApproval(
        approval["test_id"], approval["authorization_ref"], "owner", 0, "0" * 64, "No paid calls"
    )
    permission = ExecutionPermission(
        approval["authorization_ref"], quote.fingerprint, "owner", quote.expires_at_epoch
    )
    journal_path = store.root / f"{stage}-journal.jsonl"
    # An existing journal blocks repeat dispatch even after timeout/crash/HTTP error.
    with journal_path.open("x", encoding="utf-8") as journal:

        def append(event: dict[str, Any]) -> None:
            journal.write(canonical(event).decode() + "\n")
            journal.flush()
            os.fsync(journal.fileno())

        held = reserve(
            minutes,
            BudgetAccount(approval["test_id"], 0, cap),
            quote.quote_id,
            quote,
            permission,
            now,
        )
        append(
            {
                "event": "reserved",
                "minutes": held.minutes.as_dict(),
                "budget": held.budget.as_dict(),
                "quote": quote.as_dict(),
            }
        )
        dispatched = mark_dispatched(
            held.minutes, held.budget, quote.quote_id, quote.quote_id + ":attempt1", now
        )
        append({"event": "in_flight", "reservation": dispatched.reservation.as_dict()})

        def gate(current: Any) -> None:
            fresh = json.loads((store.root / "approval.json").read_text(encoding="utf-8"))
            if (
                current != dispatched.reservation
                or fresh != approval
                or fresh["expires_at_epoch"] <= time.time()
            ):
                raise ProviderError("approved_test_revoked_or_changed")

        variable = "ELEVENLABS_API_KEY" if stage == "transcript" else "GROQ_API_KEY"
        credential = os.environ.pop(variable, "")
        for name in VARIABLES:
            os.environ.pop(name, None)
        transport = BoundedProviders(credentials={provider: credential}, authorize=gate)
        result = (
            transport.transcribe(dispatched.reservation, data)
            if body is None
            else transport.generate(dispatched.reservation, body)
        )
        # Raw native response retained byte-for-byte, separate from derived display data.
        with (store.root / f"{stage}-native.json").open("xb") as native:
            native.write(result.raw_json)
            native.flush()
            os.fsync(native.fileno())
        receipt: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "http_status": 200,
            "attempts": 1,
            "source_sha256": source.source_sha256,
            "input_sha256": digest,
            "response_sha256": result.response_sha256,
            "request_id": result.request_id,
            "usage": result.usage,
            "max_paid_paise": 0,
            "credit_purchases": 0,
            "provider_charge_reconciliation": "pending",
            "private_outputs": True,
        }
        if stage == "transcript":
            transcript = scribe_transcript(
                result, duration_ms=approval["duration_ms"], source_sha256=source.source_sha256
            )
            write_private(store.root / "transcript.json", transcript)
            receipt.update(
                segment_count=len(transcript["segments"]),
                text_characters=len(transcript["raw_text"]),
            )
        uncertain = mark_uncertain(
            dispatched.minutes,
            dispatched.budget,
            quote.quote_id,
            "awaiting-provider-usage-reconciliation",
        )
        append(
            {
                "event": "response_saved",
                "receipt": receipt,
                "reservation": uncertain.reservation.as_dict(),
            }
        )
        write_private(store.root / f"{stage}-receipt.json", receipt)
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-directory", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.stage not in {"transcript", *(f"report-{i}" for i in range(1, 9))}:
        raise SystemExit("Invalid bounded test stage")
    if args.child:
        try:
            print(json.dumps(execute(args.private_directory, args.stage), allow_nan=False))
        except Exception as error:
            # No traceback/source/remote error text or key-containing repr.
            print(
                json.dumps(
                    {
                        "stage": args.stage,
                        "completed": False,
                        "error_code": str(error)
                        if isinstance(error, ProviderError)
                        else "private_test_failed",
                    }
                )
            )
            raise SystemExit(1) from None
        return
    environment = os.environ.copy()
    for name in VARIABLES:
        os.environ.pop(name, None)
    command = [
        sys.executable,
        "-m",
        "ac_platform.conversation_intelligence.approved_call_test",
        "--private-directory",
        str(args.private_directory),
        "--stage",
        args.stage,
        "--child",
    ]
    try:
        child = subprocess.run(  # noqa: S603 - fixed module and validated stage, no shell
            command, env=environment, capture_output=True, timeout=240, check=False
        )
        # Only the child's bounded JSON receipt may be returned. Never emit stderr.
        value = (
            json.loads(child.stdout)
            if len(child.stdout) < 8192
            else {"error_code": "receipt_limit"}
        )
        print(json.dumps(value))
        raise SystemExit(child.returncode)
    except subprocess.TimeoutExpired:
        print(
            json.dumps(
                {
                    "stage": args.stage,
                    "completed": False,
                    "error_code": "hard_worker_deadline",
                    "retry_permitted": False,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
