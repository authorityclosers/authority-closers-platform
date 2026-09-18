"""Pure immutable checkpoint lineage; callers must authorize before every cache lookup.

Hashes identify artifacts, never permissions. This module performs no IO or inference.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

STAGE_PARENTS: dict[str, tuple[str, ...]] = {
    "C0": (),
    "C1": ("C0",),
    "C2": ("C0",),
    "C3": ("C1", "C2"),
    "C4": ("C2", "C3"),
    "C5": ("C4",),
    "C6": ("C5",),
}
CHANGE_STAGE = {
    "source": "C0",
    "permission": "C0",
    "measurement": "C1",
    "extractor": "C1",
    "transcript": "C2",
    "speech": "C2",
    "alignment": "C3",
    "attribution": "C3",
    "context": "C4",
    "offer": "C4",
    "profile": "C5",
    "judge": "C5",
    "publication": "C6",
}


def canonical(value: Any) -> bytes:
    """Canonical JSON, deliberately rejecting NaN and Infinity."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"invalid {field}")
    return value


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"invalid {field}")
    return value


@dataclass(frozen=True)
class SourceBinding:
    tenant_id: str
    recording_id: str
    source_sha256: str
    source_revision: str

    def __post_init__(self) -> None:
        for field in ("tenant_id", "recording_id", "source_revision"):
            require_text(getattr(self, field), field)
        require_sha256(self.source_sha256, "source_sha256")


@dataclass(frozen=True)
class Checkpoint:
    binding: SourceBinding
    stage: str
    revision: str
    config_json: str
    parents: tuple[tuple[str, str], ...]
    payload_sha256: str
    replicate: str = ""

    def __post_init__(self) -> None:
        if self.stage not in STAGE_PARENTS:
            raise ValueError("unknown checkpoint stage")
        require_text(self.revision, "revision")
        require_sha256(self.payload_sha256, "payload_sha256")
        if type(self.parents) is not tuple or any(type(p) is not tuple for p in self.parents):
            raise ValueError("parents must be immutable tuples")
        if tuple(p[0] for p in self.parents) != STAGE_PARENTS[self.stage]:
            raise ValueError("checkpoint requires exact stage parents")
        for _, key in self.parents:
            require_sha256(key, "parent key")
        config = json.loads(self.config_json)
        if not isinstance(config, dict) or canonical(config).decode() != self.config_json:
            raise ValueError("config must be canonical object JSON")
        _validate_stage_config(self.stage, config)
        if not isinstance(self.replicate, str) or len(self.replicate) > 512:
            raise ValueError("invalid replicate")

    @property
    def cache_key(self) -> str:
        """Input identity excludes output hash; changed outputs need an explicit new replicate."""
        return content_hash(
            {
                "schema": "ac.sales_xray.checkpoint/1",
                "binding": asdict(self.binding),
                "stage": self.stage,
                "revision": self.revision,
                "config": json.loads(self.config_json),
                "parents": self.parents,
                "replicate": self.replicate,
            }
        )

    @property
    def manifest_sha256(self) -> str:
        return content_hash({"cache_key": self.cache_key, "payload_sha256": self.payload_sha256})

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "config": json.loads(self.config_json),
            "cache_key": self.cache_key,
            "manifest_sha256": self.manifest_sha256,
        }


def _validate_stage_config(stage: str, config: dict[str, Any]) -> None:
    # Do not accept a global recipe in a cheap stage: it would cause paid ASR cache misses.
    acoustic_keys = {
        "acoustic_profile",
        "window_profile",
        "measurement_profile",
        "source_window_profile",
        "signallab_profile",
        "audioatlas_profile",
    }
    pending: list[tuple[Any, int]] = [(config, 0)]
    visited = 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if depth > 16 or visited > 4096:
            raise ValueError("checkpoint configuration exceeds bounded complexity")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("configuration keys must be strings")
                lowered = key.lower()
                is_acoustic = stage == "C1" and lowered in acoustic_keys
                if (
                    stage not in {"C5", "C6"}
                    and not is_acoustic
                    and any(term in lowered for term in ("profile", "judge", "rubric", "coach"))
                ):
                    raise ValueError("coaching configuration belongs in C5, not source checkpoints")
                pending.append((child, depth + 1))
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)


def build_checkpoint(
    binding: SourceBinding,
    stage: str,
    revision: str,
    config: dict[str, Any],
    parents: list[Checkpoint] | tuple[Checkpoint, ...],
    payload_sha256: str,
    *,
    replicate: str = "",
) -> Checkpoint:
    if stage not in STAGE_PARENTS:
        raise ValueError("unknown checkpoint stage")
    by_stage = {parent.stage: parent for parent in parents}
    if len(by_stage) != len(parents) or set(by_stage) != set(STAGE_PARENTS[stage]):
        raise ValueError("checkpoint requires exact stage parents")
    if any(parent.binding != binding for parent in parents):
        raise ValueError("cross-source or cross-tenant parent")
    _validate_stage_config(stage, config)
    return Checkpoint(
        binding,
        stage,
        revision,
        canonical(config).decode(),
        tuple((name, by_stage[name].manifest_sha256) for name in STAGE_PARENTS[stage]),
        payload_sha256,
        replicate,
    )


def assert_same_artifact(existing: Checkpoint, candidate: Checkpoint) -> None:
    """Use under the persistence layer's unique cache-key lock; never overwrite history."""
    if existing.cache_key != candidate.cache_key:
        raise ValueError("different cache inputs")
    if existing.manifest_sha256 != candidate.manifest_sha256:
        raise ValueError("immutable checkpoint conflict; create a new revision or replicate")


def invalidated_stages(changed: set[str]) -> frozenset[str]:
    invalid: set[str] = set()
    for change in changed:
        stage = CHANGE_STAGE.get(change, change)
        if stage not in STAGE_PARENTS:
            raise ValueError("unknown changed layer")
        invalid.add(stage)
    while True:
        descendants = {s for s, parents in STAGE_PARENTS.items() if invalid.intersection(parents)}
        if descendants <= invalid:
            return frozenset(invalid)
        invalid.update(descendants)
