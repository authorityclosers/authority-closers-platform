"""Canonical, persistence-independent catalog content hashing.

The digest deliberately covers only learner-visible, versioned catalog
content. Provenance is validated separately at publication so changing a
review record never changes the identity of otherwise identical content.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

CATALOG_CONTENT_DIGEST_VERSION: Final = "ac-catalog-content-v1"


@dataclass(frozen=True, slots=True)
class CanonicalActivityContent:
    position: int
    kind: str
    title: str
    is_required: bool
    prompt: str | None


@dataclass(frozen=True, slots=True)
class CanonicalModuleContent:
    position: int
    title: str
    prerequisite_positions: tuple[int, ...]
    activities: tuple[CanonicalActivityContent, ...]


def _text_part(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return str(len(encoded)).encode("ascii") + b":" + encoded


def canonical_catalog_content_digest(
    *,
    program_slug: str,
    program_title: str,
    modules: tuple[CanonicalModuleContent, ...],
) -> str:
    """Hash one deterministic program/module/activity content projection."""

    payload = bytearray(CATALOG_CONTENT_DIGEST_VERSION.encode("ascii") + b"\n")
    payload.extend(b"P|" + _text_part(program_slug) + b"|" + _text_part(program_title) + b"\n")
    for module in sorted(modules, key=lambda item: item.position):
        prerequisites = b",".join(
            str(position).encode("ascii") for position in sorted(module.prerequisite_positions)
        )
        payload.extend(
            b"M|"
            + str(module.position).encode("ascii")
            + b"|"
            + _text_part(module.title)
            + b"|R["
            + prerequisites
            + b"]\n"
        )
        for activity in sorted(module.activities, key=lambda item: item.position):
            prompt = b"N" if activity.prompt is None else b"S" + _text_part(activity.prompt)
            payload.extend(
                b"A|"
                + str(module.position).encode("ascii")
                + b"|"
                + str(activity.position).encode("ascii")
                + b"|"
                + _text_part(activity.kind)
                + b"|"
                + _text_part(activity.title)
                + b"|"
                + (b"1" if activity.is_required else b"0")
                + b"|"
                + prompt
                + b"\n"
            )
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "CATALOG_CONTENT_DIGEST_VERSION",
    "CanonicalActivityContent",
    "CanonicalModuleContent",
    "canonical_catalog_content_digest",
]
