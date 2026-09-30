"""Content-free failure detail for failed provider jobs (``ac.job-failure-detail/1``).

A dead-lettered provider job keeps one ``last_error`` code, and the catch-all
``conversation_provider_result_validation_failed`` hides which rule fired.
Worker logs do not survive a container restart, so the worker also stores a
small, content-free description of the exception chain on the job row:

- ``failure_code``: exactly what ``last_error`` gets;
- ``code``: the innermost source-owned code in the chain (``args[0]`` of
  ``InferenceTaskError``, ``ReportError``, ``ProviderError``, ``OpenAITaskError``
  or ``GeminiTaskError``), kept only when it is a short identifier;
- ``site``: the innermost ``ac_platform`` frame as ``file.py:line:function``,
  skipping the bare ``_fail`` raise helpers so the frame names the rule;
- ``errors``: up to ten pydantic ``{"loc", "type"}`` pairs found in the chain,
  with schema keys and integer indices only;
- ``validator_revision``: the report validator revision for C4 and C5.

The chain follows ``__cause__`` and then ``__context__`` (also when the context
was suppressed with ``raise ... from None``), because the task layer re-raises
report errors that way and the suppressed pydantic error is the diagnosis.
Nothing here copies an exception message, provider text, transcript text, a
report, or a person's name or id. Building the detail never raises: any error
inside the builder yields the minimal ``{"schema", "failure_code"}`` detail.
"""

from __future__ import annotations

import json
import re
import traceback
from pathlib import PurePath
from typing import Any

from pydantic import ValidationError

from ac_platform.conversation_intelligence.reports import REPORT_VALIDATOR_REVISION

FAILURE_DETAIL_SCHEMA = "ac.job-failure-detail/1"
FAILURE_DETAIL_MAX_BYTES = 2048
REDACTED = "<redacted>"
_REDACTED_KEY = "<key>"
_MAX_ERRORS = 10
_MAX_CHAIN = 8
_CODE = re.compile(r"[a-z0-9_]{1,60}")
_KEY = re.compile(r"[A-Za-z0-9_]{1,40}")
_FRAME_PART = re.compile(r"[A-Za-z0-9_.<>]{1,80}")
_SOURCE_OWNED = frozenset(
    {"InferenceTaskError", "ReportError", "ProviderError", "OpenAITaskError", "GeminiTaskError"}
)
_RAISE_HELPERS = frozenset({"_fail"})
_STAGES = frozenset({"C2", "C4", "C5"})
_VALIDATED_STAGES = frozenset({"C4", "C5"})


def minimal_failure_detail(failure_code: str) -> dict[str, Any]:
    """The detail stored when nothing beyond the failure code can be kept."""

    return {"schema": FAILURE_DETAIL_SCHEMA, "failure_code": failure_code}


def build_failure_detail(
    error: BaseException | None,
    *,
    stage: str | None,
    failure_code: str,
) -> dict[str, Any]:
    """Describe ``error`` without content. Never raises; falls back to the minimal detail."""

    try:
        detail = _describe(error, stage=stage, failure_code=failure_code)
        return _bounded(detail, failure_code=failure_code)
    except Exception:
        try:
            return _bounded(minimal_failure_detail(failure_code), failure_code=failure_code)
        except Exception:
            return minimal_failure_detail(REDACTED)


def canonical_failure_detail(detail: dict[str, Any]) -> str:
    """Canonical ASCII JSON, so the byte length equals the character length."""

    return json.dumps(detail, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _describe(
    error: BaseException | None,
    *,
    stage: str | None,
    failure_code: str,
) -> dict[str, Any]:
    code: str | None = None
    site: str | None = None
    errors: list[dict[str, str]] = []
    for item in _chain(error):
        if _is_source_owned(item) and item.args:
            code = _safe_code(item.args[0])
        frame = _innermost_site(item)
        if frame is not None:
            site = frame
        if isinstance(item, ValidationError) and len(errors) < _MAX_ERRORS:
            entries = item.errors(include_url=False, include_context=False, include_input=False)
            for entry in entries[: _MAX_ERRORS - len(errors)]:
                errors.append(
                    {"loc": _loc(entry.get("loc", ())), "type": _safe_code(entry.get("type"))}
                )
    known_stage = stage if stage in _STAGES else None
    return {
        "schema": FAILURE_DETAIL_SCHEMA,
        "stage": known_stage,
        "failure_code": failure_code,
        "code": code,
        "validator_revision": (
            REPORT_VALIDATOR_REVISION if known_stage in _VALIDATED_STAGES else None
        ),
        "site": site,
        "errors": errors,
    }


def _chain(error: BaseException | None) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current = error
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _is_source_owned(error: BaseException) -> bool:
    return any(cls.__name__ in _SOURCE_OWNED for cls in type(error).__mro__)


def _safe_code(value: object) -> str:
    if isinstance(value, str) and _CODE.fullmatch(value) is not None:
        return value
    return REDACTED


def _loc(parts: object) -> str:
    if not isinstance(parts, list | tuple):
        return _REDACTED_KEY
    return ".".join(_key(part) for part in parts)


def _key(part: object) -> str:
    if isinstance(part, bool):
        return _REDACTED_KEY
    if isinstance(part, int):
        return str(part)
    if isinstance(part, str) and _KEY.fullmatch(part) is not None:
        return part
    return _REDACTED_KEY


def _innermost_site(error: BaseException) -> str | None:
    frames = [
        frame
        for frame in traceback.extract_tb(error.__traceback__)
        if "ac_platform" in PurePath(frame.filename).parts
    ]
    while len(frames) > 1 and frames[-1].name in _RAISE_HELPERS:
        frames.pop()
    if not frames:
        return None
    frame = frames[-1]
    name = PurePath(frame.filename).name
    if (
        frame.lineno is None
        or _FRAME_PART.fullmatch(name) is None
        or _FRAME_PART.fullmatch(frame.name) is None
    ):
        return None
    return f"{name}:{frame.lineno}:{frame.name}"


def _fits(detail: dict[str, Any]) -> bool:
    return len(canonical_failure_detail(detail)) <= FAILURE_DETAIL_MAX_BYTES


def _bounded(detail: dict[str, Any], *, failure_code: str) -> dict[str, Any]:
    if _fits(detail):
        return detail
    trimmed = dict(detail)
    while trimmed.get("errors") and not _fits(trimmed):
        trimmed["errors"] = list(trimmed["errors"])[:-1]
    if _fits(trimmed):
        return trimmed
    for field in ("site", "code"):
        if field in trimmed:
            trimmed[field] = None
    if _fits(trimmed):
        return trimmed
    minimal = minimal_failure_detail(failure_code)
    return minimal if _fits(minimal) else minimal_failure_detail(REDACTED)
