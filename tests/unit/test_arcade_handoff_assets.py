"""Copied candidate assets retain exact handoff bytes and inert local formats."""

from __future__ import annotations

import hashlib
import re
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "apps/learner-web/public/arcade-v02"
HASHES = {
    "checkpoint-seal.svg": "99e261240caa43915cc9799bb5a1c1cd4f5e87018c83b2179a7e74fbb5b733c7",
    "clarity-lens.svg": "e8a880135d78e7e59ffd34b58c08f1a10ce452ed952aabf4ffece83f432aac44",
    "discovery-compass.svg": "81dc8fc8102c273e3761df7b109879f249fcb6c774018ea128cb78253ae021a8",
    "league-banner.svg": "2bb11025305f3c42923501038c233bba99a4b5fd2f2b7a90ae35719f175ae4fc",
    "listening-arc.svg": "580d3a38b00d43cde68e17e622e2e36f360b19bc60ff5f39e66db71e1930e2c9",
    "pair-tiles.svg": "de8806722b9fab003e6490528025e69fc0f6aed94311906da25861b78773a970",
    "revision-folio.svg": "047948b22d0a12d08dbce407046fb9527e04234e039497989c09859b4314c5b6",
    "squad-orbit.svg": "b03571d05d2d9691682f3f3e9b7d70d604bdd9b5811de4153137f82714c9f76c",
    "listen-01.wav": "d2d718d914234bdd4047b18a048a1168f233aa442e3423e624b71bd828c8a275",
    "listen-02.wav": "22ecf5281bf2e6b9edbf085b6aed7c7f867eb605482ae54679a81a05a04d3cb2",
    "listen-03.wav": "ccdd8c6d3deba45d959ed34364cd37ec2a9cb03448bfdd0e00b55a2c22099e73",
}


@pytest.mark.parametrize("name,expected", HASHES.items())
def test_candidate_asset_matches_source_bytes(name, expected):
    assert hashlib.sha256((ASSETS / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("name", [name for name in HASHES if name.endswith(".svg")])
def test_vectors_are_static_and_have_no_external_resource_references(name):
    source = (ASSETS / name).read_text(encoding="utf-8")
    assert not re.search(r"<!DOCTYPE|<!ENTITY|<script|<foreignObject", source, re.I)
    root = ET.fromstring(source)  # noqa: S314 - exact hashed local bytes; DTD/entity rejected above
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    for element in root.iter():
        for attribute, value in element.attrib.items():
            local_name = attribute.split("}")[-1].lower()
            assert not local_name.startswith("on")
            assert local_name != "href"
            assert not re.search(r"url\(\s*[\"']?(?!#)", value, re.I)


@pytest.mark.parametrize("name", [name for name in HASHES if name.endswith(".wav")])
def test_fictional_audio_is_finite_uncompressed_pcm(name):
    with wave.open(str(ASSETS / name)) as audio:
        assert audio.getcomptype() == "NONE"
        assert audio.getnchannels() in (1, 2)
        assert 1 < audio.getnframes() / audio.getframerate() < 60
