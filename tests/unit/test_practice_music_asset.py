"""Offline integrity, provenance and resource bounds for optional CC0 music."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "apps/learner-web/public/audio/practice"
MANIFEST = json.loads((ASSETS / "music-manifest.json").read_text(encoding="utf-8"))


def test_music_is_one_small_same_origin_source_pinned_loop() -> None:
    path = ASSETS / MANIFEST["file"]
    raw = path.read_bytes()

    assert path.name == "overworld-loop.mp3"
    assert MANIFEST["url"] == "/audio/practice/overworld-loop.mp3"
    assert len(raw) == MANIFEST["bytes"] == 275_424
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == MANIFEST["sha256"] == MANIFEST["source_sha256"]
    assert digest == "d32949f8467ac463a52ca88ed250e505545bc98a46e4e472c1f994bf447a1beb"
    assert raw.startswith(b"\xff\xfb")
    assert 9_700 < MANIFEST["duration_ms"] < 9_900
    assert MANIFEST["measured_peak_dbfs"] <= -10
    assert MANIFEST["transformation"] == "Renamed only; source bytes are unchanged."


def test_music_license_and_primary_author_provenance_are_explicit() -> None:
    assert MANIFEST["license"] == "CC0-1.0"
    assert MANIFEST["license_url"] == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert MANIFEST["page_url"] == "https://opengameart.org/content/overworld-bgm"
    assert MANIFEST["download_url"] == ("https://opengameart.org/sites/default/files/overworld.mp3")
    assert MANIFEST["author"] == "IntelligentGene / Another Page Studio"
    assert MANIFEST["auditioned"] is False
    assert "loop" in MANIFEST["source_description"].lower()

    notice = (ASSETS / "MUSIC_LICENSE.md").read_text(encoding="utf-8")
    for required in (
        "IntelligentGene",
        "Another Page Studio",
        "CC0",
        MANIFEST["page_url"],
        MANIFEST["license_url"],
        "No endorsement",
    ):
        assert required in notice


def test_music_manifest_matches_measured_media_shape() -> None:
    assert MANIFEST["container"] == "MP3"
    assert MANIFEST["codec"] == "mp3"
    assert MANIFEST["sample_rate_hz"] == 48_000
    assert MANIFEST["channels"] == 2
    assert MANIFEST["average_bit_rate"] == 223_922
    assert MANIFEST["measured_mean_dbfs"] == pytest.approx(-24.1)
