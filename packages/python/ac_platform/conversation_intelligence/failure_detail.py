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
- ``errors``: up to ten pydantic ``{"loc", "type"}`` pairs found in the chain.
  Each location is walked through the model that raised the error: a part is
  kept only when that model's schema declares it at that position (a field name,
  a list index, or a union member's model name). A mapping key, an unexpected
  extra key, or any part under an unknown schema becomes ``<key>``, because a
  provider chose it and it can carry a name or an id;
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
import types
from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

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
            model = _validating_model(item)
            entries = item.errors(include_url=False, include_context=False, include_input=False)
            for entry in entries[: _MAX_ERRORS - len(errors)]:
                kind = _safe_code(entry.get("type"))
                errors.append({"loc": _loc(entry.get("loc", ()), kind, model), "type": kind})
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


def _loc(parts: object, kind: str | None = None, model: object = None) -> str:
    """Walk ``parts`` through ``model``; keep only what its schema declares at each position."""

    if not isinstance(parts, list | tuple):
        return _REDACTED_KEY
    keys: list[str] = []
    node: object = model
    for part in parts:
        text, node = _step(node, part)
        keys.append(text)
    if kind == "extra_forbidden" and keys:
        # The last element of an extra-forbidden location is the provider's own key.
        keys[-1] = _REDACTED_KEY
    return ".".join(keys)


def _step(node: object, part: object) -> tuple[str, object]:
    """One location part under the schema ``node``: (kept text or ``<key>``, schema below it)."""

    candidates = _members(node)
    if isinstance(part, bool):
        return _REDACTED_KEY, None
    if isinstance(part, int):
        return str(part), _first(_item_type(c) for c in candidates)
    if not isinstance(part, str) or _KEY.fullmatch(part) is None:
        return _REDACTED_KEY, None
    mapping = next((c for c in candidates if _is_mapping(c)), None)
    if mapping is not None:
        # Any key of a mapping is provider data, whatever word it happens to be.
        args = get_args(mapping)
        return _REDACTED_KEY, args[1] if len(args) == 2 else None
    for candidate in candidates:
        if _is_model(candidate):
            for name, field in candidate.model_fields.items():
                if part in (name, field.alias, field.validation_alias):
                    return part, field.annotation
    for candidate in candidates:
        if _is_model(candidate) and candidate.__name__ == part:
            return part, candidate  # a union member tag names the member model
    return _REDACTED_KEY, None


def _members(node: object) -> list[object]:
    """``node`` with Annotated and Optional/Union unwrapped; empty when unknown."""

    if node is None:
        return []
    origin = get_origin(node)
    if origin is Annotated:
        return _members(get_args(node)[0])
    if origin is Union or isinstance(node, types.UnionType):
        return [m for arg in get_args(node) for m in _members(arg) if m is not type(None)]
    return [node]


def _first(values: Any) -> object:
    return next((value for value in values if value is not None), None)


def _is_model(node: object) -> bool:
    return isinstance(node, type) and issubclass(node, BaseModel)


def _is_mapping(node: object) -> bool:
    origin = get_origin(node) or node
    return isinstance(origin, type) and issubclass(origin, Mapping)


def _item_type(node: object) -> object:
    origin = get_origin(node) or node
    if not isinstance(origin, type) or not issubclass(origin, Sequence) or issubclass(origin, str | bytes):
        return None
    args = get_args(node)
    return args[0] if args else None


def _validating_model(error: ValidationError) -> type[BaseModel] | None:
    """The one loaded model named by the error's title, else None (and every key is redacted)."""

    matches = [model for model in _models() if model.__name__ == error.title]
    return matches[0] if len(matches) == 1 else None


def _models() -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    stack: list[type[BaseModel]] = list(BaseModel.__subclasses__())
    seen: set[type[BaseModel]] = set()
    while stack:
        model = stack.pop()
        if model in seen:
            continue
        seen.add(model)
        found.append(model)
        stack.extend(model.__subclasses__())
    return found


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
