"""Model transports for the one-pass pipeline. Google only.

- ``GoogleGemini``: the Gemini API (generativelanguage.googleapis.com), the route real
  calls take. Standard or Flex (``service_tier: flex``: half price, best effort, may
  queue for minutes). Flex answers 429/503 when busy; after a few tries the request
  falls back to standard once, and the run records that it did.
- ``OpenRouterBench``: Google AI Studio through OpenRouter, for the fictional benchmark
  calls only (the research's account, while the bench project's own Gemini key is
  refused). Never used for a real call: the runner only builds it in ``--bench`` mode.

Keys come from the process environment, which only the ``infisical run`` child has.
Nothing here logs prompts, answers, audio or keys; failures carry fixed codes only.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import httpx

from ac_platform.one_pass.pricing import Usage, usage_from_gemini, usage_from_openrouter

GEMINI: Final = "https://generativelanguage.googleapis.com"
OPENROUTER: Final = "https://openrouter.ai/api/v1/chat/completions"
INLINE_AUDIO_BYTES: Final = 14 * 1024 * 1024  # base64 grows a third; requests stay under 20 MB
TRANSIENT: Final = frozenset({429, 500, 502, 503, 504})
AUDIO_TOKENS_PER_SECOND: Final = 32  # Gemini's audio tokenisation


class OnePassFailure(RuntimeError):
    """A failed request with a stable, content-free outcome code."""

    def __init__(self, outcome: str, usage: Usage | None = None) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.usage = usage


@dataclass(frozen=True, slots=True)
class Request:
    system: str
    user: str
    schema: dict[str, Any] | None
    max_output_tokens: int
    temperature: float | None = None
    thinking: str = "LOW"
    audio: bytes | None = field(default=None, repr=False)
    audio_mime: str | None = None
    audio_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class Reply:
    data: dict[str, Any] = field(repr=False)
    usage: Usage
    tier_used: str  # standard | flex | flex_fell_back
    attempts: int
    ms: int
    finish: str | None
    response_sha256: str
    schema_mode: str = "strict"  # strict | prompt (the schema was refused and sent as text)
    provider_cost_usd: float | None = None  # what the provider billed, when it says


class Transport(Protocol):
    name: str

    def generate(self, *, model: str, request: Request, tier: str) -> Reply: ...


def decode_answer(text: str | None, usage: Usage, finish: str | None) -> dict[str, Any]:
    if finish == "MAX_TOKENS":
        raise OnePassFailure("answer_too_long", usage)
    if not text:
        raise OnePassFailure("empty_answer", usage)
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else body[3:]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    try:
        value = json.loads(body)
    except ValueError:
        raise OnePassFailure("unreadable_answer", usage) from None
    if not isinstance(value, dict):
        raise OnePassFailure("unreadable_answer", usage)
    return value


class GoogleGemini:
    """The Gemini API, standard or Flex."""

    name = "gemini"

    def __init__(
        self,
        key: str | None = None,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        flex_tries: int = 3,
        standard_tries: int = 3,
    ) -> None:
        self._key = key if key is not None else os.environ.get("GEMINI_API_KEY", "")
        self._client = client
        self._sleep = sleep
        self._flex_tries = flex_tries
        self._standard_tries = standard_tries

    @property
    def ready(self) -> bool:
        return bool(self._key)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(follow_redirects=False, trust_env=False)
        return self._client

    def _upload(self, audio: bytes, mime: str) -> tuple[str, str]:
        """Files API (resumable) for audio too large to send inline; (uri, name)."""
        http = self._http()
        try:
            start = http.post(
                f"{GEMINI}/upload/v1beta/files",
                headers={
                    "x-goog-api-key": self._key,
                    "X-Goog-Upload-Protocol": "resumable",
                    "X-Goog-Upload-Command": "start",
                    "X-Goog-Upload-Header-Content-Length": str(len(audio)),
                    "X-Goog-Upload-Header-Content-Type": mime,
                },
                json={"file": {"display_name": "call-audio"}},
                timeout=60,
            )
            upload_url = start.headers.get("x-goog-upload-url")
            if start.status_code != 200 or not upload_url:
                raise OnePassFailure(f"upload_http_{start.status_code}")
            done = http.post(
                upload_url,
                headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"},
                content=audio,
                timeout=600,
            )
            if done.status_code != 200:
                raise OnePassFailure(f"upload_http_{done.status_code}")
            info = done.json().get("file") or {}
            for _ in range(60):
                if info.get("state") in (None, "ACTIVE"):
                    break
                if info.get("state") == "FAILED":
                    raise OnePassFailure("upload_failed")
                self._sleep(2)
                info = http.get(
                    f"{GEMINI}/v1beta/{info['name']}",
                    headers={"x-goog-api-key": self._key},
                    timeout=30,
                ).json()
            return str(info["uri"]), str(info["name"])
        except httpx.HTTPError:
            raise OnePassFailure("upload_transport_error") from None
        except (KeyError, TypeError, ValueError):
            raise OnePassFailure("upload_unreadable") from None

    def _delete(self, name: str) -> None:
        """Best effort: uploaded audio is removed at once (Google also expires it in 48 h)."""
        with contextlib.suppress(httpx.HTTPError):
            self._http().delete(
                f"{GEMINI}/v1beta/{name}", headers={"x-goog-api-key": self._key}, timeout=30
            )

    def _body(self, request: Request, audio_part: dict[str, Any] | None, *, schema: bool) -> Any:
        config: dict[str, Any] = {
            "candidateCount": 1,
            "maxOutputTokens": request.max_output_tokens,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": request.thinking, "includeThoughts": False},
        }
        if request.temperature is not None:
            config["temperature"] = request.temperature
        system = request.system
        if request.schema is not None:
            if schema:
                config["responseJsonSchema"] = request.schema
            else:
                system += "\n\nReturn JSON that matches this JSON schema exactly:\n" + json.dumps(
                    request.schema, separators=(",", ":")
                )
        parts: list[dict[str, Any]] = [audio_part] if audio_part is not None else []
        parts.append({"text": request.user})
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": config,
        }

    def _post(self, model: str, body: dict[str, Any], tier: str) -> httpx.Response:
        payload = {**body, "service_tier": "flex"} if tier == "flex" else body
        try:
            return self._http().post(
                f"{GEMINI}/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": self._key, "content-type": "application/json"},
                json=payload,
                # Flex may queue: Google advises ten minutes or more.
                timeout=httpx.Timeout(900.0 if tier == "flex" else 300.0, connect=20.0),
            )
        except httpx.TimeoutException:
            raise OnePassFailure("timeout") from None
        except httpx.HTTPError:
            raise OnePassFailure("transport_error") from None

    def generate(self, *, model: str, request: Request, tier: str) -> Reply:
        if not self._key:
            raise OnePassFailure("credential_missing")
        uploaded: str | None = None
        audio_part: dict[str, Any] | None = None
        if request.audio is not None:
            mime = request.audio_mime or "application/octet-stream"
            if len(request.audio) <= INLINE_AUDIO_BYTES:
                audio_part = {
                    "inline_data": {
                        "mime_type": mime,
                        "data": base64.b64encode(request.audio).decode("ascii"),
                    }
                }
            else:
                uri, uploaded = self._upload(request.audio, mime)
                audio_part = {"file_data": {"mime_type": mime, "file_uri": uri}}
        try:
            return self._generate(model, request, audio_part, tier)
        finally:
            if uploaded is not None:
                self._delete(uploaded)

    def _generate(
        self, model: str, request: Request, audio_part: dict[str, Any] | None, tier: str
    ) -> Reply:
        clock = time.monotonic()
        schema_mode = "strict"
        body = self._body(request, audio_part, schema=True)
        plan = [tier] * (self._flex_tries if tier == "flex" else self._standard_tries)
        if tier == "flex":
            plan.append("standard")  # one fallback, billed at standard and recorded
        attempts = 0
        status = 0
        response: httpx.Response | None = None
        used = tier
        for index, current in enumerate(plan):
            attempts += 1
            response = self._post(model, body, current)
            status = response.status_code
            used = current
            if status == 400 and schema_mode == "strict" and request.schema is not None:
                # A refused request with a structured-output schema is most often the
                # schema itself (too complex, or a keyword the route can't take; Google
                # then says only "invalid argument"): send it as text once, so the answer
                # still follows it and is validated here. A refused request is not billed.
                schema_mode = "prompt"
                body = self._body(request, audio_part, schema=False)
                response = self._post(model, body, current)
                attempts += 1
                status = response.status_code
            if status == 200 or status not in TRANSIENT:
                break
            if index + 1 < len(plan):
                self._sleep(min(60.0, 5.0 * (3**index)))
        if response is None or status != 200:
            raise OnePassFailure(f"provider_http_{status}")
        raw = response.content
        try:
            data = response.json()
            usage = usage_from_gemini(data.get("usageMetadata"))
            candidate = data["candidates"][0]
            finish = candidate.get("finishReason")
            text = "".join(
                part.get("text", "")
                for part in candidate.get("content", {}).get("parts", [])
                if not part.get("thought")
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise OnePassFailure("unreadable_response") from None
        answer = decode_answer(text, usage, finish)
        return Reply(
            data=answer,
            usage=usage,
            tier_used="flex_fell_back" if tier == "flex" and used == "standard" else used,
            attempts=attempts,
            ms=round((time.monotonic() - clock) * 1000),
            finish=finish,
            response_sha256=hashlib.sha256(raw).hexdigest(),
            schema_mode=schema_mode,
        )


class OpenRouterBench:
    """Google AI Studio through OpenRouter: fictional benchmark calls only."""

    name = "openrouter-google"

    def __init__(
        self,
        key: str | None = None,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._key = key if key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self._client = client or httpx.Client(follow_redirects=False, trust_env=False)
        self._sleep = sleep

    @property
    def ready(self) -> bool:
        return bool(self._key)

    def generate(self, *, model: str, request: Request, tier: str) -> Reply:
        if not self._key:
            raise OnePassFailure("credential_missing")
        content: list[dict[str, Any]] = []
        if request.audio is not None:
            if request.audio_mime not in {"audio/mpeg", "audio/mp3", "audio/wav"}:
                raise OnePassFailure("bench_audio_format")
            content.append(
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": base64.b64encode(request.audio).decode("ascii"),
                        "format": "wav" if request.audio_mime == "audio/wav" else "mp3",
                    },
                }
            )
        content.append({"type": "text", "text": request.user})
        body: dict[str, Any] = {
            "model": f"google/{model}",
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": content},
            ],
            "max_tokens": request.max_output_tokens,
            "reasoning": {"effort": request.thinking.lower()},
            "usage": {"include": True},
            # Google AI Studio only (its list prices; Vertex's differ), and no provider that
            # keeps prompts for training.
            "provider": {
                "order": ["google-ai-studio"],
                "allow_fallbacks": False,
                "data_collection": "deny",
            },
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        schema_mode = "strict"
        if request.schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": False, "schema": request.schema},
            }
        clock = time.monotonic()
        attempts = 0
        response: httpx.Response | None = None
        for index in range(4):
            attempts += 1
            try:
                response = self._client.post(
                    OPENROUTER,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "X-Title": "AC one-pass benchmark",
                    },
                    json=body,
                    timeout=httpx.Timeout(900.0, connect=20.0),
                )
            except httpx.TimeoutException:
                raise OnePassFailure("timeout") from None
            except httpx.HTTPError:
                raise OnePassFailure("transport_error") from None
            if response.status_code == 400 and schema_mode == "strict" and request.schema:
                # Through this route Google AI Studio answers "invalid argument" to the
                # one pass's combined schema (21 Oct 2026; the transcript's small schema is
                # taken): JSON mode with the schema as text, once, as the research ran it.
                # The answer is validated here either way; a refused request is not billed.
                schema_mode = "prompt"
                body["response_format"] = {"type": "json_object"}
                body["messages"][0]["content"] = (
                    request.system
                    + "\n\nReturn JSON that matches this JSON schema exactly:\n"
                    + json.dumps(request.schema, separators=(",", ":"))
                )
                continue
            if response.status_code not in TRANSIENT:
                break
            self._sleep(min(60.0, 5.0 * (3**index)))
        if response is None or response.status_code != 200:
            raise OnePassFailure(f"provider_http_{response.status_code if response else 0}")
        try:
            data = response.json()
            usage = usage_from_openrouter(data.get("usage"))
            choice = data["choices"][0]
            finish = choice.get("finish_reason")
            text = choice["message"].get("content")
            billed = (data.get("usage") or {}).get("cost")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise OnePassFailure("unreadable_response") from None
        if request.audio is not None and usage.audio == 0 and request.audio_seconds:
            # OpenRouter does not always split audio tokens out; Gemini counts 32 a second.
            audio = min(usage.prompt, round(request.audio_seconds * AUDIO_TOKENS_PER_SECOND))
            usage = Usage(usage.prompt, audio, usage.cached, usage.output, usage.thoughts)
        answer = decode_answer(text, usage, "MAX_TOKENS" if finish == "length" else finish)
        return Reply(
            data=answer,
            usage=usage,
            tier_used="standard",
            attempts=attempts,
            ms=round((time.monotonic() - clock) * 1000),
            finish=finish,
            response_sha256=hashlib.sha256(response.content).hexdigest(),
            schema_mode=schema_mode,
            provider_cost_usd=float(billed) if isinstance(billed, int | float) else None,
        )
