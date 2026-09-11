"""Offline integrity, provenance and resource bounds for optional CC0 UI cues."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "apps/learner-web/public/audio/practice"
MANIFEST = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
EXPECTED_HASHES = {
    "select.wav": "12bbfde9fec219439ae042c11aa66b50dc10121452a62e4e8ad33c0293de4697",
    "confirm.wav": "fb30cc1cda28b8e4450ec05cf6737b34a6fb938e3fdcaa45dbaee5a262981d1e",
    "retry.wav": "9b8f860d011b448698647ce5d058072712e339033bfdf10fe64d250c21ee4708",
    "reward.wav": "d15ff5364db61db28d9ce4373931cfa60cec414d8f56cdb42aa1aead719c8eb1",
}
EXPECTED_SOURCES = {
    "interface-sounds": (
        "https://opengameart.org/content/interface-sounds",
        "https://opengameart.org/sites/default/files/kenney_interfaceSounds.zip",
        "f2193d072726d6758a5f7871b2dcc54dcce0d5c35c6f0a62f92549b327c81232",
    ),
    "music-jingles": (
        "https://kenney.nl/assets/music-jingles",
        "https://kenney.nl/media/pages/assets/music-jingles/f37e530b9e-1677590399/kenney_music-jingles.zip",
        "b729ba57959bd58793d2c5cafa348aaf2655d354f3da35ec4729e03ec77197b8",
    ),
}
EXPECTED_ENTRIES = {
    "select.wav": (
        "interface-sounds",
        "Audio/click_002.ogg",
        "adcd1f4adc35f1b41bc1b5bbefeff7aa44f2f3f0d96d3199b544140c7c1e761c",
    ),
    "confirm.wav": (
        "interface-sounds",
        "Audio/confirmation_001.ogg",
        "063564703b6094d70718a3e787a55cc9141611e4ecd6b6637f8828f79b4a8c3a",
    ),
    "retry.wav": (
        "interface-sounds",
        "Audio/question_001.ogg",
        "abb8f9e4eb2071491b0b15f84ee302386b1847609310c1b000ae174639a6cc5a",
    ),
    "reward.wav": (
        "music-jingles",
        "Audio/Pizzicato jingles/jingles_PIZZI00.ogg",
        "b442ade3308a2bbda4b8c572c86f9f1071c7bdbcfb1e6f915d35c605b61bd475",
    ),
}


def test_audio_pack_is_small_local_and_exactly_four_optional_cues():
    assert {path.name for path in ASSETS.glob("*.wav")} == set(EXPECTED_HASHES)
    assert {asset["file"] for asset in MANIFEST["assets"]} == set(EXPECTED_HASHES)
    total = sum((ASSETS / filename).stat().st_size for filename in EXPECTED_HASHES)
    assert total == MANIFEST["total_audio_bytes"] == 113628
    assert sum(path.stat().st_size for path in ASSETS.iterdir() if path.is_file()) < 400_000
    assert MANIFEST["auditioned"] is False
    assert MANIFEST["license"] == "CC0-1.0"
    assert MANIFEST["license_url"] == "https://creativecommons.org/publicdomain/zero/1.0/"
    for asset in MANIFEST["assets"]:
        assert asset["url"] == f"/audio/practice/{asset['file']}"
        assert asset["cue"] == Path(asset["file"]).stem


@pytest.mark.parametrize("asset", MANIFEST["assets"], ids=lambda asset: asset["cue"])
def test_decoded_pcm_duration_hash_and_restrained_peak(asset):
    path = ASSETS / asset["file"]
    raw = path.read_bytes()
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    assert len(raw) == asset["bytes"]
    assert hashlib.sha256(raw).hexdigest() == asset["sha256"] == EXPECTED_HASHES[path.name]
    with wave.open(str(path)) as audio:
        assert audio.getcomptype() == "NONE"
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 44100
        assert audio.getnframes() == asset["frames"]
        duration = audio.getnframes() / audio.getframerate()
        assert 0.005 < duration < 1.5
        assert duration * 1000 == pytest.approx(asset["duration_ms"], abs=0.001)
        pcm = audio.readframes(audio.getnframes())
    # Minimal WAV header, no embedded metadata, URLs or additional payload.
    assert len(raw) == 44 + len(pcm)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    peak = max(abs(sample) for sample in samples)
    assert 0 < peak < 32767
    assert max(samples) > 0 and min(samples) < 0
    dbfs = 20 * math.log10(peak / 32768)
    assert dbfs <= -10
    assert dbfs == pytest.approx(asset["measured_peak_dbfs"], abs=0.15)


def test_source_archive_entry_and_license_provenance_are_pinned():
    assert set(MANIFEST["sources"]) == set(EXPECTED_SOURCES)
    for key, (page, download, archive_hash) in EXPECTED_SOURCES.items():
        source = MANIFEST["sources"][key]
        assert source["page_url"] == page
        assert source["download_url"] == download
        assert source["archive_sha256"] == archive_hash
        assert source["license_entry"] == "License.txt"
        assert source["license"] == "CC0-1.0"
    for asset in MANIFEST["assets"]:
        assert (asset["source"], asset["source_entry"], asset["source_sha256"]) == EXPECTED_ENTRIES[
            asset["file"]
        ]
    notice = (ASSETS / "LICENSE.md").read_text(encoding="utf-8")
    assert "Kenney" in notice and "CC0" in notice and "No endorsement" in notice
    assert "https://creativecommons.org/publicdomain/zero/1.0/" in notice
