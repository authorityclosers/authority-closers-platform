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
  a list or fixed-tuple index with that position's own schema, or a union
  member's container label). Pydantic's union branch label is consumed as a
  label, never as a key, and a union with a model or TypedDict member (which
  may be tagged by a discriminator) hides everything below its label. A mapping key of any type, an
  unexpected extra key, or any part under an unknown schema or an unresolved
  union branch becomes ``<key>``, because a provider chose it and it can carry a
  name or an id. Only the report models the provider pipeline validates are
  supported roots; any other root (a type adapter, a root model, a title another
  class shares) keeps nothing in the location, and so does a field name that is
  also another field's alias or a nested root model;
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
from collections.abc import Mapping, Sequence, Set
from pathlib import PurePath
from typing import Annotated, Any, TypeGuard, Union, get_args, get_origin

from pydantic import BaseModel, RootModel, ValidationError

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.report_overview import DetailedOverview
from ac_platform.conversation_intelligence.reports import REPORT_VALIDATOR_REVISION

FAILURE_DETAIL_SCHEMA = "ac.job-failure-detail/1"
FAILURE_DETAIL_MAX_BYTES = 2048
REDACTED = "<redacted>"
_REDACTED_KEY = "<key>"
# Below a union branch that cannot be resolved safely, nothing more is kept.
_OPAQUE = object()
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

    if node is _OPAQUE:
        return _REDACTED_KEY, _OPAQUE
    candidates = _members(node)
    if len(candidates) > 1:
        # Pydantic names the union branch first; that label is not an input key.
        return _branch(candidates, part)
    if not candidates:
        # No supported root schema: an integer could be a mapping key as easily
        # as an index, so nothing in this location is kept.
        return _REDACTED_KEY, _OPAQUE
    single = candidates[0]
    if _is_mapping(single):
        # Any key of a mapping is provider data, whatever its type or word: a
        # string, an integer, or a word some model declares elsewhere.
        args = get_args(single)
        return _REDACTED_KEY, args[1] if len(args) == 2 else _OPAQUE
    if _is_model(single) and issubclass(single, RootModel):
        return _REDACTED_KEY, _OPAQUE  # its "root" position is the provider's own data
    if isinstance(part, int) and not isinstance(part, bool) and _is_sequence(single):
        item = _item_schema(single, part)
        if item is not _OPAQUE:
            return str(part), item
    if isinstance(part, str) and _KEY.fullmatch(part) is not None and _is_model(single):
        matches = [
            field
            for name, field in single.model_fields.items()
            if part in (name, field.alias, field.validation_alias)
        ]
        if len(matches) == 1:  # a name that is also another field's alias is ambiguous
            return part, matches[0].annotation
    # Inside a known schema, a part it does not declare at this position hides the rest.
    return _REDACTED_KEY, _OPAQUE


def _branch(candidates: list[object], label: object) -> tuple[str, object]:
    """Resolve a union branch label to its member; an unresolved branch hides what follows."""

    if not isinstance(label, str) or any(_may_be_tagged(c) for c in candidates):
        # A tagged union labels its branch with the discriminator value, which
        # can name any member (or none); such a branch is never resolved here.
        return _REDACTED_KEY, _OPAQUE
    kind = _BRANCH_KINDS.get(label.split("[", 1)[0])
    if kind is not None:
        matches = [candidate for candidate in candidates if kind(candidate)]
        if len(matches) == 1:
            return _REDACTED_KEY, matches[0]
    return _REDACTED_KEY, _OPAQUE


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


def _is_model(node: object) -> TypeGuard[type[BaseModel]]:
    return isinstance(node, type) and issubclass(node, BaseModel)


def _may_be_tagged(node: object) -> bool:
    """Members a discriminated union can hold: models and TypedDicts."""

    return _is_model(node) or (
        isinstance(node, type) and issubclass(node, dict) and hasattr(node, "__required_keys__")
    )


def _is_mapping(node: object) -> bool:
    origin = get_origin(node) or node
    return isinstance(origin, type) and issubclass(origin, Mapping)


def _is_sequence(node: object) -> bool:
    origin = get_origin(node) or node
    return (
        isinstance(origin, type)
        and issubclass(origin, Sequence | Set)
        and not issubclass(origin, str | bytes)
    )


_BRANCH_KINDS = {
    "dict": _is_mapping,
    "Mapping": _is_mapping,
    "list": _is_sequence,
    "tuple": _is_sequence,
    "set": _is_sequence,
    "frozenset": _is_sequence,
}


def _item_schema(node: object, index: int) -> object:
    """The item schema at ``index``: a fixed tuple by position, a sequence by its argument."""

    origin = get_origin(node) or node
    args = get_args(node)
    if isinstance(origin, type) and issubclass(origin, tuple):
        if len(args) == 2 and args[1] is Ellipsis:
            return args[0]
        return args[index] if 0 <= index < len(args) else _OPAQUE
    return args[0] if len(args) == 1 else _OPAQUE


def _validating_model(error: ValidationError) -> type[BaseModel] | None:
    """The source-owned report model that raised ``error``, else None (every part is redacted).

    Only the closed set of report models the provider pipeline validates is
    supported. A title is just a word, so another loaded class answering to it
    (by name or configured title) makes it ambiguous, and the location is hidden.
    """

    model = _supported_roots().get(error.title)
    if model is None:
        return None
    for other in _models():
        if other is not model and error.title in (other.__name__, other.model_config.get("title")):
            return None
    return model


def _supported_roots() -> dict[str, type[BaseModel]]:
    roots = (
        reports.FactPacket,
        reports.AggregateFactPacket,
        reports.ReportDraft,
        reports.ReportCitation,
        DetailedOverview,
    )
    return {root.__name__: root for root in roots if not root.model_config.get("title")}


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
