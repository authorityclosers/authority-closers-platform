"""What the coaching lead reviews in a call's Report, item by item (owner, 23 Oct 2026).

The owner: "a pipeline where dipak can easily review each single thing … designed in such
a way that it's flexible so next time if report, analysis structure, coaching and
everything changes, automatically the review pipeline adapts".

The items come from the Report's own structure (``report-structure/1`` with its AI
overlays: Brain 4.0's 18 skills, the call outcome, the buyer's signals and profile), read
through a registry (``profiles/review_schema.json``) that names each section, where it
sits and how its items read. The registry is data: when the Report changes, the file
changes, not the code. A top-level section the registry does not know yet is still
reviewed, as one item, so nothing new is ever left out.

An item says what the AI said (a 1-5 rating or words, a detail line, the lines it cites);
the reviewer agrees, disagrees or fixes it, with a note. Item ids are stable within a
call's saved Report and carry their section (``brain4.D04``, ``outcome.next_steps.2``).

Pure: no I/O but reading the registry file.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REGISTRY_FILE: Final = Path(__file__).with_name("profiles") / "review_schema.json"
TEXT_KEYS: Final = ("text", "note", "value", "summary", "reason")
MAX_TEXT: Final = 600
MAX_ITEMS: Final = 200
WHOLE: Final = "whole"


@functools.cache
def registry() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    if not isinstance(document.get("sections"), list) or not document.get("version"):
        raise ValueError("review_schema_invalid")
    return document


@functools.cache
def digest() -> str:
    return hashlib.sha256(REGISTRY_FILE.read_bytes()).hexdigest()[:16]


def meta(structure: Mapping[str, Any]) -> dict[str, Any]:
    """The versions a review is bound to: the Report's structure and this registry."""
    version = structure.get("version")
    return {
        "structure": version if isinstance(version, str) else None,
        "registry": registry()["version"],
        "digest": digest(),
    }


def _at(structure: Mapping[str, Any], path: Sequence[str]) -> Any:
    value: Any = structure
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def text_of(value: Any, keys: Sequence[str] = ()) -> str | None:
    """Words to show for a value: a string, the first text-like field, or a short list."""
    if isinstance(value, str):
        return _clip(value) if value.strip() else None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Mapping):
        for key in (*keys, *TEXT_KEYS):
            found = text_of(value.get(key))
            if found:
                return found
        return None
    if isinstance(value, list):
        parts = [part for part in (text_of(item, keys) for item in value[:8]) if part]
        return _clip("; ".join(parts)) if parts else None
    return None


def _detail(value: Any, keys: Sequence[str]) -> str | None:
    if not isinstance(value, Mapping):
        return None
    parts = []
    for key in keys:
        found = text_of(value.get(key))
        if found:
            parts.append(found if key in ("coaching",) else f"{key.replace('_', ' ')}: {found}")
    return _clip(" · ".join(parts)) if parts else None


def _rating(value: Any, keys: Sequence[str]) -> int | None:
    if not isinstance(value, Mapping):
        return None
    for key in keys:
        rating = value.get(key)
        if type(rating) is int and 1 <= rating <= 5:
            return rating
    return None


def _evidence(value: Any) -> list[dict[str, Any]]:
    refs = value.get("evidence") if isinstance(value, Mapping) else None
    found = []
    for ref in refs if isinstance(refs, list) else []:
        if isinstance(ref, Mapping) and isinstance(ref.get("quote"), str):
            item: dict[str, Any] = {"quote": _clip(ref["quote"])}
            for key in ("segment_id", "start_ms", "end_ms"):
                if key in ref:
                    item[key] = ref[key]
            found.append(item)
    return found[:2]


def _label(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _item(
    section: Mapping[str, Any], suffix: str, label: str, value: Any, number: int | None = None
) -> dict[str, Any] | None:
    rating_keys = section.get("rating_keys") or ()
    rated = bool(rating_keys)
    text = text_of(value, section.get("text_keys") or ())
    rating = _rating(value, rating_keys)
    if not rated and not text:
        return None
    item: dict[str, Any] = {
        "id": f"{section['id']}.{suffix}",
        "section": section["id"],
        "label": label,
        "kind": "rating" if rated else "text",
        "rating": rating,
        "text": text,
        "detail": _detail(value, section.get("detail_keys") or ()),
        "evidence": _evidence(value),
    }
    if number is not None:
        item["number"] = number
    return item


def _section_items(
    section: Mapping[str, Any], structure: Mapping[str, Any]
) -> list[dict[str, Any]]:
    value = _at(structure, section["path"])
    kind = section.get("kind")
    found: list[dict[str, Any] | None] = []
    if kind == "list" and isinstance(value, list):
        for index, element in enumerate(value, 1):
            key = section.get("id_key")
            raw_id = element.get(key) if key and isinstance(element, Mapping) else None
            suffix = str(raw_id) if isinstance(raw_id, str | int) and raw_id != "" else str(index)
            label_keys = section.get("label_keys") or ()
            label = text_of(element, label_keys) if label_keys else None
            number = None
            if isinstance(element, Mapping) and section.get("number_key"):
                number = element.get(section["number_key"])
            found.append(
                _item(
                    section,
                    suffix,
                    label or f"{section['label']} {index}",
                    element,
                    number if type(number) is int else None,
                )
            )
    elif kind == "fields" and isinstance(value, Mapping):
        for key, label in (section.get("fields") or {}).items():
            if key in value:
                found.append(_item(section, key, label, value[key]))
    elif kind == "map" and isinstance(value, Mapping):
        skip = set(section.get("skip_keys") or ())
        for key, element in value.items():
            if key not in skip:
                found.append(_item(section, key, _label(key), element))
    return [item for item in found if item is not None]


def items(structure: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every reviewable item in a call's Report structure, in the Report's order: the
    registry's sections first, then any section it does not know, as one item each."""
    document = registry()
    covered = {section["path"][0] for section in document["sections"]}
    skip = set(document.get("skip") or ())
    found: list[dict[str, Any]] = []
    for section in document["sections"]:
        found.extend(_section_items(section, structure))
    for key, value in structure.items():
        if key in covered or key in skip:
            continue
        text = text_of(value)
        if text:
            found.append(
                {
                    "id": f"{key}.{WHOLE}",
                    "section": key,
                    "label": _label(key),
                    "kind": "text",
                    "rating": None,
                    "text": text,
                    "detail": None,
                    "evidence": _evidence(value),
                }
            )
    return found[:MAX_ITEMS]


def section_label(section: str) -> str:
    """A section's name: the registry's, else one made from its key."""
    for known in registry()["sections"]:
        if known["id"] == section:
            return str(known["label"])
    return _label(section)


def sections(found: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Items grouped under their section's name, in order."""
    grouped: dict[str, dict[str, Any]] = {}
    for item in found:
        section = grouped.setdefault(
            item["section"],
            {"id": item["section"], "label": section_label(item["section"]), "items": []},
        )
        section["items"].append(dict(item))
    return list(grouped.values())


def route_module(section: str, route: Mapping[str, Any]) -> str:
    """The analysis engine module (``analysis_engine.registry``) behind a section."""
    if section == "brain4":
        source = route.get("brain4") or ""
        return "c4.one-pass-v2" if str(source).startswith("review:") else "b4.shadow"
    review = str(route.get("review") or "")
    if review.startswith("automatic:one-pass-plan"):
        return "c4.one-pass-v1.luna-flex" if "luna" in review else "c4.one-pass-v1"
    return "pr.classic"


__all__ = ["digest", "items", "meta", "registry", "route_module", "sections", "text_of"]
