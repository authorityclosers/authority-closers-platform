"""Run the real hosted native helper against a synthetic one-second WAV.

Run as the database worker UID10001 with its socket/scratch mappings, without
DB/provider credentials. The helper/container execute their actual confinement
preflight. This command never creates a Docker connection in the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ac_platform.conversation_intelligence.native_runtime import (
    NativeRuntimeError,
    SocketNativeRuntime,
)

try:
    from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
except ImportError:
    # The release helper transport intentionally contains only the runtime
    # boundary and its signal parser. A full application checkout can run the
    # exact upload preflight; the minimal helper bundle cannot import it.
    NativeUploadPreflight = None  # type: ignore[assignment,misc]


def _validate_source_measurement(
    result: dict[str, object], *, source_sha256: str, source_bytes: int
) -> None:
    decoded = result.get("decoded")
    if not isinstance(decoded, dict):
        raise ValueError("unexpected_validation_result")
    if (
        result.get("schema") != "ac.sales-xray.source-validation/1"
        or result.get("source_sha256") != source_sha256
        or result.get("source_bytes") != source_bytes
        or result.get("media_duration_ms") != 1000
        or decoded.get("sample_count") != 16000
        or decoded.get("channels") != 1
    ):
        raise ValueError("unexpected_validation_result")


def _validate_inspection(
    result: dict[str, object], *, source_sha256: str, source_bytes: int
) -> None:
    timebase = result.get("timebase")
    native_receipt = result.get("native_receipt")
    if not isinstance(timebase, dict) or not isinstance(native_receipt, dict):
        raise ValueError("unexpected_synthetic_result")
    if (
        result.get("source_sha256") != source_sha256
        or result.get("source_bytes") != source_bytes
        or result.get("media_duration_ms") != 1000
        or timebase.get("rate") != 16000
        or native_receipt.get("rows") != 100
    ):
        raise ValueError("unexpected_synthetic_result")


def main() -> int:
    parser = argparse.ArgumentParser(description="Real Linux native-helper synthetic smoke")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        if sys.platform != "linux" or os.getuid() != 10001 or os.getgid() != 10001:
            raise ValueError("worker_identity_required")
        os.umask(0o077)
        runtime = SocketNativeRuntime(
            socket_path=args.socket,
            workspace_root=args.workspace_root,
            expected_image_ref=args.image_ref,
        )
        with tempfile.TemporaryDirectory(prefix="smoke-", dir=args.workspace_root) as folder:
            workspace = Path(folder)
            source = workspace / "source.wav"
            samples = b"".join(
                struct.pack("<h", int(8192 * math.sin(2 * math.pi * 440 * n / 16000)))
                for n in range(16000)
            )
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(samples)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            successful_runs = 0
            validated = runtime.validate_source(
                source, workspace / "validated", job_id=uuid4(), rate=16000
            )
            _validate_source_measurement(
                validated, source_sha256=digest, source_bytes=source.stat().st_size
            )
            successful_runs += 1
            inspected = runtime.inspect(source, workspace / "result", job_id=uuid4(), rate=16000)
            _validate_inspection(
                inspected, source_sha256=digest, source_bytes=source.stat().st_size
            )
            successful_runs += 1
            if (workspace / "validated" / "features.aaf").exists():
                raise ValueError("validation_published_features")
            if not (workspace / "validated" / "checkpoint.json").is_file():
                raise ValueError("validation_receipt_missing")

            preflight_measured = False
            if NativeUploadPreflight is not None:
                measured = NativeUploadPreflight(runtime).measure(source, uuid4(), digest)
                if (
                    measured.source.source_sha256 != digest
                    or measured.source.duration_ms != 1000
                    or measured.intent.source_bytes != source.stat().st_size
                    or measured.intent.content_type != "audio/wav"
                ):
                    raise ValueError("unexpected_upload_measurement")
                successful_runs += 1
                preflight_measured = True
            wrong_image = "sha256:" + ("0" if not args.image_ref.endswith("0" * 64) else "1") * 64
            mismatch = SocketNativeRuntime(
                socket_path=args.socket,
                workspace_root=args.workspace_root,
                expected_image_ref=wrong_image,
            )
            for operation, output_name in (
                ("validate_source", "rejected-validate"),
                ("inspect", "rejected-inspect"),
            ):
                try:
                    getattr(mismatch, operation)(
                        source, workspace / output_name, job_id=uuid4(), rate=16000
                    )
                except NativeRuntimeError:
                    pass
                else:
                    raise ValueError("unapproved_native_image_accepted")
            # The helper must remain usable after a rejected request.
            again = runtime.inspect(source, workspace / "again", job_id=uuid4(), rate=16000)
            _validate_inspection(again, source_sha256=digest, source_bytes=source.stat().st_size)
            successful_runs += 1
            if again["feature_sha256"] != inspected["feature_sha256"]:
                raise ValueError("native_result_not_deterministic")
        receipt = {
            "schema": "ac.sales_xray.hosted_native_smoke/1",
            "observed_at": datetime.now(UTC).isoformat(),
            "status": "passed",
            "fixture": "synthetic-1s-440hz-mono-16khz",
            "image_ref": args.image_ref,
            "source_sha256": digest,
            "feature_sha256": inspected["feature_sha256"],
            "native_receipt": inspected["native_receipt"],
            "profile_rate": 16000,
            "duration_ms": 1000,
            "native_runs": successful_runs,
            "validated": True,
            "inspected": True,
            "upload_preflight_measured": preflight_measured,
            "wrong_image_rejected": True,
            "helper_usable_after_rejection": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "provider_calls": 0,
            "database_connections": 0,
        }
        # Exclusive creation prevents overwriting an earlier release receipt.
        with args.receipt.open("x", encoding="utf-8") as target:
            target.write(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        print("hosted_native_smoke_passed")
        return 0
    except Exception:
        print("hosted_native_smoke_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
