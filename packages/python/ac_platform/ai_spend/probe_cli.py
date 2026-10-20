"""The release canary's cheap path: prove each provider works for about one paisa.

Owner, 20 Oct 2026: releases ran one full C1–C6 analysis of the fixture call each
time (6–8 a day per environment on 16–19 Oct, about ₹2–3.4 each). The host canary
(``infra/vps-foundation/scripts/ac-canary``) now runs that full analysis at most once
a day per environment, and otherwise this probe, inside the worker container:

- Gemini: one fixed 7-word generateContent on the approved model, at most 16 output
  tokens. A 402 (prepaid credit used up), 429 or 403 shows here exactly as in a real
  analysis, so a release never goes out on a dead key unnoticed.
- ElevenLabs: the free subscription read (no transcription).

Each provider's key exists only in its own ``infisical run`` child, started with the
worker's service config and its launcher, exactly like the pointer review. Nothing
printed holds a key, a response body or anything but status codes and token counts.

    python -m ac_platform.ai_spend.probe_cli \\
        --service-config /run/ac-sales-xray/service.json --environment staging
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import ssl
import subprocess  # noqa: S404 - fixed argv, no shell
import sys
import time
from pathlib import Path
from typing import Any

INNER = "--inner"
GEMINI_HOST = "generativelanguage.googleapis.com"
ELEVENLABS_HOST = "api.elevenlabs.io"
PROMPT = "Reply with the single word OK."
MAX_OUTPUT_TOKENS = 16
CHILD_SECONDS = 60
# Gemini 3.8 Flash list price (admin_pricing), ₹100 per dollar: paise per token.
_PAISE_IN = 0.75 * 100 * 100 / 1_000_000
_PAISE_OUT = 3.75 * 100 * 100 / 1_000_000


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ai_spend.probe_cli")
    parser.add_argument("--service-config", required=True, type=Path)
    parser.add_argument(
        "--environment", required=True, choices=("development", "staging", "production")
    )
    parser.add_argument("--gemini-model", default="gemini-3.8-flash")
    parser.add_argument("--provider", choices=("gemini", "elevenlabs"), help=argparse.SUPPRESS)
    parser.add_argument(INNER, action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if not arguments.gemini_model.replace("-", "").replace(".", "").isalnum():
        parser.error("--gemini-model is a model id such as gemini-3.8-flash")
    return arguments


def _connection(host: str) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(host, timeout=20, context=ssl.create_default_context())


def probe_gemini(model: str, key: str) -> dict[str, Any]:
    """One fixed tiny request; only the status and token counts are kept."""
    record: dict[str, Any] = {"provider": "gemini", "model": model}
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": PROMPT}]}],
            "generationConfig": {
                "candidateCount": 1,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
                "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
            },
        }
    )
    connection = _connection(GEMINI_HOST)
    try:
        connection.request(
            "POST",
            f"/v1beta/models/{model}:generateContent",
            body=body,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        record["http_status"] = response.status
        if response.status == 200:
            usage = json.loads(response.read(64 * 1024)).get("usageMetadata") or {}
            tokens_in = int(usage.get("promptTokenCount") or 0)
            tokens_out = int(usage.get("candidatesTokenCount") or 0) + int(
                usage.get("thoughtsTokenCount") or 0
            )
            record["tokens"] = [tokens_in, tokens_out]
            record["cost_paise"] = math.ceil(tokens_in * _PAISE_IN + tokens_out * _PAISE_OUT)
    except (OSError, ValueError, http.client.HTTPException):
        record["error"] = "network"
    finally:
        connection.close()
    record["ok"] = record.get("http_status") == 200
    return record


def probe_elevenlabs(key: str) -> dict[str, Any]:
    """The free subscription read: the key works and the account is usable."""
    record: dict[str, Any] = {"provider": "elevenlabs"}
    connection = _connection(ELEVENLABS_HOST)
    try:
        connection.request(
            "GET",
            "/v1/user/subscription",
            headers={"xi-api-key": key, "Accept": "application/json"},
        )
        response = connection.getresponse()
        record["http_status"] = response.status
        if response.status == 200:
            status = json.loads(response.read(64 * 1024)).get("status")
            if isinstance(status, str) and len(status) < 40:
                record["status"] = status
    except (OSError, ValueError, http.client.HTTPException):
        record["error"] = "network"
    finally:
        connection.close()
    record["ok"] = record.get("http_status") == 200 and record.get("status") not in {
        "cancelled",
        "past_due",
        "unpaid",
    }
    record["cost_paise"] = 0
    return record


def _inner(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.provider == "gemini":
        key = os.environ.pop("GEMINI_API_KEY", "")
        return probe_gemini(arguments.gemini_model, key) if key else _missing("gemini")
    key = os.environ.pop("ELEVENLABS_API_KEY", "")
    return probe_elevenlabs(key) if key else _missing("elevenlabs")


def _missing(provider: str) -> dict[str, Any]:
    return {"provider": provider, "ok": False, "error": "credential_missing"}


def _child(provider: dict[str, Any], argv: list[str]) -> dict[str, Any]:
    """Run this module once inside ``infisical run`` for one provider's secret path."""
    name = str(provider["provider_id"])
    try:
        token = Path(provider["token_file_ref"]).read_text().strip()
    except OSError:
        return {"provider": name, "ok": False, "error": "identity_unreadable"}
    if token.startswith("INFISICAL_TOKEN="):
        token = token[len("INFISICAL_TOKEN=") :]
    environment = {
        key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG"}
    }
    environment["INFISICAL_TOKEN"] = token
    command = [
        str(provider.get("executable") or "/usr/local/bin/infisical"),
        "run",
        "--include-imports=false",
        "--expand=false",
        "--silent",
        "--telemetry=false",
        "--log-level=error",
        "--projectId",
        str(provider["project_ref"]),
        "--env",
        str(provider["environment_ref"]),
        "--path",
        str(provider["secret_path_ref"]),
        "--",
        sys.executable,
        "-m",
        "ac_platform.ai_spend.probe_cli",
        *argv,
        "--provider",
        name,
        INNER,
    ]
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=CHILD_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"provider": name, "ok": False, "error": "probe_unavailable"}
    try:
        record = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"provider": name, "ok": False, "error": "probe_no_result"}
    return record if isinstance(record, dict) else {"provider": name, "ok": False}


def probe(arguments: argparse.Namespace, argv: list[str]) -> dict[str, Any]:
    started = time.monotonic()
    service = json.loads(arguments.service_config.read_text())
    providers = {
        str(item.get("provider_id")): item
        for item in service.get("providers") or []
        if item.get("provider_id") in {"gemini", "elevenlabs"}
    }
    records = [
        _child(providers[name], argv) if name in providers else _missing(name)
        for name in ("gemini", "elevenlabs")
    ]
    failed = next((item for item in records if not item.get("ok")), None)
    failure = None
    if failed is not None:
        detail = failed.get("http_status") or failed.get("error") or "failed"
        failure = f"probe_{failed['provider']}_{'http_' if isinstance(detail, int) else ''}{detail}"
    return {
        "ok": failed is None,
        "mode": "probe",
        "environment": arguments.environment,
        "stage_reached": "probe",
        "failure_code": failure,
        "providers": records,
        "cost_paise": sum(int(item.get("cost_paise") or 0) for item in records),
        "report_present": False,
        "total_seconds": round(time.monotonic() - started, 3),
    }


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(raw)
    if arguments.inner:
        print(json.dumps(_inner(arguments), sort_keys=True))
        return 0
    passed = [item for item in raw if item != INNER]
    result = probe(arguments, passed)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
