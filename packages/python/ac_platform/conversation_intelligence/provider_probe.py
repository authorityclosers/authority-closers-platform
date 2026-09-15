"""Bounded metadata-only provider probe, run separately through scoped Infisical injection.

No generation, transcription, media input, purchase, retries, arbitrary URLs or
response-body logging. This module is excluded from the offline worker image.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
from datetime import UTC, datetime
from typing import Any

TARGETS = (
    (
        "elevenlabs",
        "ELEVENLABS_API_KEY",
        "api.elevenlabs.io",
        "/v1/user/subscription",
        "xi-api-key",
    ),
    (
        "gemini",
        "GEMINI_API_KEY",
        "generativelanguage.googleapis.com",
        "/v1beta/models",
        "x-goog-api-key",
    ),
    ("groq", "GROQ_API_KEY", "api.groq.com", "/openai/v1/models", "Authorization"),
    ("sarvam", "SARVAM_API_KEY", "api.sarvam.ai", "/v2/models", "api-subscription-key"),
)
MAX_RESPONSE_BYTES = 512 * 1024


def probe_accounts(only_provider: str | None = None) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for provider, variable, host, path, header in TARGETS:
        if only_provider is not None and provider != only_provider:
            continue
        credential = os.environ.pop(variable, None)
        record: dict[str, Any] = {"provider": provider, "credential_injected": bool(credential)}
        records.append(record)
        if not credential:
            continue
        connection = http.client.HTTPSConnection(
            host, timeout=15, context=ssl.create_default_context()
        )
        try:
            value = f"Bearer {credential}" if header == "Authorization" else credential
            connection.request("GET", path, headers={header: value, "Accept": "application/json"})
            response = connection.getresponse()
            record["http_status"] = response.status
            # No redirect following and no error-body reads/logging.
            if response.status != 200:
                continue
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                record["error"] = "response_size_limit"
                continue
            data = json.loads(raw)
            if provider == "elevenlabs":
                for name in (
                    "tier",
                    "status",
                    "character_count",
                    "character_limit",
                    "can_extend_character_limit",
                    "allowed_to_extend_character_limit",
                    "max_credit_limit_extension",
                    "next_character_count_reset_unix",
                ):
                    field = data.get(name)
                    if (
                        field is None
                        or isinstance(field, (bool, int))
                        or isinstance(field, str)
                        and len(field) < 40
                    ):
                        record[name] = field
                record["authentication_proven"] = True
            else:
                models = data.get("models", data.get("data", []))
                record["model_count"] = len(models) if isinstance(models, list) else None
                if provider == "gemini" and isinstance(models, list):
                    record["generation_models"] = [
                        entry["name"]
                        for entry in models
                        if isinstance(entry, dict)
                        and isinstance(entry.get("name"), str)
                        and entry["name"].startswith("models/gemini-")
                        and len(entry["name"]) < 100
                        and "generateContent" in entry.get("supportedGenerationMethods", [])
                    ]
                record["authentication_proven"] = provider != "sarvam"
                record["billing_tier_verified"] = False
                # Sarvam's discovery docs describe the endpoint as unauthenticated.
        except Exception:
            record["error"] = "metadata_probe_failed"
        finally:
            connection.close()
            credential = None
    return {
        "schema": "ac.sales_xray.provider_metadata/1",
        "captured_at": datetime.now(UTC).isoformat(),
        "generation_calls": 0,
        "recording_bytes_sent": 0,
        "purchases": 0,
        "providers": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=[target[0] for target in TARGETS])
    print(json.dumps(probe_accounts(parser.parse_args().provider), allow_nan=False))
