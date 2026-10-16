"""Simulated calls pick a fictional recording in the lead's language, from its business."""

import json
from pathlib import Path

from ac_platform.lead_desk.simulation import audio_path, catalogue, language_codes, pick


def _root(tmp_path: Path) -> str:
    rows = [
        ("syn-saas-J01-C-01", "hi-en", "syn-saas", "DarpanDesk Cloud"),
        ("syn-saas-J02-C-01", "mr-en", "syn-saas", "DarpanDesk Cloud"),
        ("syn-estate-J01-C-01", "en-IN", "syn-estate", "Estate Autopilots"),
        ("syn-naya-J01-C-01", "hi-mr-en", "syn-naya", "Naya Growth / Kriya"),
    ]
    entries = []
    for sample_id, mix, business, name in rows:
        (tmp_path / f"{sample_id}.mp3").write_bytes(b"ID3")
        entries.append(
            {
                "sample_id": sample_id,
                "file": f"{sample_id}.mp3",
                "language_mix": mix,
                "business_id": business,
                "business_name": name,
                "duration_ms": 180_000,
            }
        )
    entries.append({**entries[0], "sample_id": "syn-missing", "file": "syn-missing.mp3"})
    entries.append({**entries[0], "sample_id": "../escape", "file": "../escape.mp3"})
    (tmp_path / "catalogue.json").write_text(json.dumps(entries))
    return str(tmp_path)


def test_catalogue_keeps_only_present_safe_recordings(tmp_path: Path) -> None:
    samples = catalogue(_root(tmp_path))
    assert [sample.sample_id for sample in samples] == [
        "syn-saas-J01-C-01",
        "syn-saas-J02-C-01",
        "syn-estate-J01-C-01",
        "syn-naya-J01-C-01",
    ]
    assert catalogue(None) == () and catalogue(str(tmp_path / "nowhere")) == ()


def test_language_then_business_decide_the_recording(tmp_path: Path) -> None:
    samples = catalogue(_root(tmp_path))
    marathi = pick(samples, language="Marathi", business=None, seed="a")
    assert marathi is not None and "mr" in marathi.languages
    own = pick(samples, language="Hindi", business="DarpanDesk Cloud", seed="b")
    assert own is not None and own.sample_id == "syn-saas-J01-C-01"
    # No recording speaks Tamil: any recording rather than none.
    assert pick(samples, language="Tamil", business=None, seed="c") is not None
    assert pick((), language="Hindi", business=None, seed="d") is None


def test_same_seed_same_choice(tmp_path: Path) -> None:
    samples = catalogue(_root(tmp_path))
    first = pick(samples, language="English", business=None, seed="lead:0")
    assert first == pick(samples, language="English", business=None, seed="lead:0")


def test_language_codes_read_names_and_mixes() -> None:
    assert language_codes("Hindi, English") == {"hi", "en"}
    assert language_codes("hi-mr-en") == {"hi", "mr", "en"}
    assert language_codes(None) == frozenset()


def test_audio_path_only_for_catalogued_ids(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert audio_path(root, "syn-saas-J01-C-01") == Path(root) / "syn-saas-J01-C-01.mp3"
    assert audio_path(root, "syn-missing") is None
    assert audio_path(root, "../escape") is None
