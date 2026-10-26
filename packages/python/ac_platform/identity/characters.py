"""Friendly characters for people without a photo, and the one a person chooses (owner #32,
26 Oct 2026; the orchestrator chose to store it with no migration).

The builder's characters live beside this module: ``characters/manifest.json`` lists them in
order, and each is a 256 px WebP file ``characters/<key>.webp``. A chosen character is kept as
the person's photo byte for byte, so the photo's sha256 says which one it is, and it shows
wherever photos already show. Anyone without a photo gets one picked from their id, the same
way on the server and in the app: the first 8 hex digits of the id, modulo the count.

A shipped file never changes (a stored choice would stop matching it); a new look is a new key.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import UUID

FOLDER = Path(__file__).with_name("characters")
KEY = re.compile(r"[a-z][a-z0-9-]{1,23}")
SIZE = 256
MAX_BYTES = 64 * 1024


@dataclass(frozen=True)
class Character:
    key: str
    label: str
    data: bytes
    sha256: str

    @property
    def url(self) -> str:
        """The picture's address; the ?v= changes only if the file does."""
        return f"/v1/people/characters/{self.key}?v={self.sha256[:8]}"


class CharacterRejected(ValueError):
    """Not one of the characters (or none have shipped yet)."""


def _checked(folder: Path, key: str, label: str) -> Character:
    from PIL import Image

    if not KEY.fullmatch(key) or key == "photo":
        raise ValueError(f"character key {key!r} must match {KEY.pattern} and not be 'photo'")
    data = (folder / f"{key}.webp").read_bytes()
    if len(data) > MAX_BYTES or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError(f"character {key!r} must be a WebP file of at most {MAX_BYTES} bytes")
    with Image.open(io.BytesIO(data)) as picture:
        if picture.size != (SIZE, SIZE):
            raise ValueError(f"character {key!r} must be {SIZE}x{SIZE}, not {picture.size}")
    name = " ".join(str(label).split())[:40]
    if not name:
        raise ValueError(f"character {key!r} needs a label")
    return Character(key, name, data, hashlib.sha256(data).hexdigest())


@lru_cache(maxsize=4)
def load(folder: Path | None = None) -> tuple[Character, ...]:
    """The characters in manifest order; none until the builder's files ship."""
    where = folder or FOLDER
    manifest = where / "manifest.json"
    if not manifest.is_file():
        return ()
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    found = tuple(_checked(where, item["key"], item["label"]) for item in spec["characters"])
    if len({item.key for item in found}) != len(found):
        raise ValueError("character keys must be unique")
    return found


def by_key(key: str) -> Character | None:
    return next((item for item in load() if item.key == key), None)


def by_sha(sha256: str | None) -> Character | None:
    """The character a stored photo is, if it is one."""
    return next((item for item in load() if item.sha256 == sha256), None) if sha256 else None


def default_for(person_id: UUID) -> Character | None:
    """The character someone without a photo shows: the first 8 hex digits of their id,
    modulo the count (the app picks the same way)."""
    found = load()
    return found[int(person_id.hex[:8], 16) % len(found)] if found else None
