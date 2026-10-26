"""The characters (owner #32, 26 Oct 2026): the builder's 256 px WebP files and their
manifest load in order, a stored photo says which character it is by its sha256, and someone
without a photo gets one picked from their id the same way the app picks it."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image

from ac_platform.identity import characters


def make(folder: Path, keys: list[str], *, size: int = 256, kind: str = "WEBP") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for index, key in enumerate(keys):
        out = io.BytesIO()
        Image.new("RGB", (size, size), (40 * index, 120, 200)).save(out, kind)
        (folder / f"{key}.webp").write_bytes(out.getvalue())
    manifest = {"version": 1, "characters": [{"key": k, "label": k.title()} for k in keys]}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


@pytest.fixture
def shipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = make(tmp_path / "characters", ["otter", "panda", "robot"])
    monkeypatch.setattr(characters, "FOLDER", folder)
    characters.load.cache_clear()
    yield folder
    characters.load.cache_clear()


def test_characters_load_in_order_and_are_found_by_key_and_sha(shipped: Path) -> None:
    found = characters.load()
    assert [item.key for item in found] == ["otter", "panda", "robot"]
    assert [item.label for item in found] == ["Otter", "Panda", "Robot"]
    panda = characters.by_key("panda")
    assert panda is not None
    assert panda.data == (shipped / "panda.webp").read_bytes()
    assert panda.sha256 == hashlib.sha256(panda.data).hexdigest()
    assert panda.url == f"/v1/people/characters/panda?v={panda.sha256[:8]}"
    assert characters.by_sha(panda.sha256) == panda
    assert characters.by_sha("0" * 64) is None and characters.by_sha(None) is None
    assert characters.by_key("dragon") is None


def test_the_default_is_the_first_eight_hex_digits_of_the_id_modulo_the_count(
    shipped: Path,
) -> None:
    for person in (
        UUID("11111111-1111-4111-8111-111111111111"),
        UUID("0000000a-0000-4000-8000-000000000000"),
        UUID("ffffffff-1234-4abc-8def-000000000000"),
    ):
        expected = characters.load()[int(person.hex[:8], 16) % 3]
        assert characters.default_for(person) == expected


@pytest.mark.parametrize(
    ("keys", "size", "kind"),
    [
        (["Otter"], 256, "WEBP"),  # a key in capitals
        (["photo"], 256, "WEBP"),  # would shadow /v1/people/{id}/photo
        (["otter"], 128, "WEBP"),  # not 256 px
        (["otter"], 256, "PNG"),  # not a WebP file
    ],
)
def test_a_wrong_file_or_key_is_refused(
    tmp_path: Path, keys: list[str], size: int, kind: str
) -> None:
    with pytest.raises(ValueError):
        characters.load.__wrapped__(make(tmp_path / "c", keys, size=size, kind=kind))


def test_duplicate_keys_are_refused_and_no_manifest_means_none(tmp_path: Path) -> None:
    folder = make(tmp_path / "c", ["otter"])
    (folder / "manifest.json").write_text(
        json.dumps({"characters": [{"key": "otter", "label": "A"}, {"key": "otter", "label": "B"}]})
    )
    with pytest.raises(ValueError):
        characters.load.__wrapped__(folder)
    assert characters.load.__wrapped__(tmp_path / "missing") == ()


def test_the_shipped_characters_are_valid() -> None:
    """Whatever the builder ships beside the module loads (256 px WebP, at most 64 KB)."""
    characters.load.cache_clear()
    found = characters.load()
    assert all(len(item.data) <= characters.MAX_BYTES for item in found)
