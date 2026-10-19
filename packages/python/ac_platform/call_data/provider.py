"""Text models for the call data engine, behind one small interface (swappable in Admin).

The provider key is read from the process environment, which only the
``infisical run`` child has (the runner re-executes itself inside it). Nothing
here logs prompts, answers or credentials.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

TIMEOUT_SECONDS = 120.0
MAX_OUTPUT_TOKENS = 12000


class ProviderFailure(RuntimeError):
    """A failed call with a stable, content-free outcome code."""

    def __init__(self, outcome: str, usage: dict[str, Any] | None = None) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.usage = usage


@dataclass(frozen=True, slots=True)
class Answer:
    value: Any
    usage: dict[str, Any]


class TextModel(Protocol):
    def generate_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any]
    ) -> Answer: ...


class Gemini:
    """Google Gemini generateContent with native JSON output."""

    def __init__(self, key: str | None = None) -> None:
        self._key = key if key is not None else os.environ.get("GEMINI_API_KEY", "")

    @property
    def ready(self) -> bool:
        return bool(self._key)

    def generate_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any]
    ) -> Answer:
        import httpx

        if not self._key:
            raise ProviderFailure("credential_missing")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "candidateCount": 1,
                "temperature": 0.1,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
                "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
            },
        }
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": self._key, "content-type": "application/json"},
                json=body,
                timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=20.0),
            )
        except httpx.TimeoutException:
            raise ProviderFailure("timeout") from None
        except httpx.HTTPError:
            raise ProviderFailure("transport_error") from None
        if response.status_code != 200:
            raise ProviderFailure(f"provider_http_{response.status_code}")
        try:
            data = dict(response.json())
        except ValueError:
            raise ProviderFailure("unreadable_response") from None
        usage = dict(data.get("usageMetadata") or {})
        try:
            candidate = data["candidates"][0]
            raw = "".join(part.get("text", "") for part in candidate["content"]["parts"])
            value = json.loads(raw)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderFailure("unreadable_answer", usage) from None
        return Answer(value=value, usage=usage)


def for_provider(provider: str) -> TextModel:
    if provider == "gemini":
        return Gemini()
    raise ProviderFailure("provider_unsupported")
