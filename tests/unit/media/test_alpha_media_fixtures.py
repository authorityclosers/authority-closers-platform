from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ac_platform.media import stress_fixtures

TOOLS = Path(__file__).resolve().parents[3] / "tools" / "media-player-stress"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_hls_ladder as hls  # noqa: E402
from fixture_harness import FixtureManifestError, load_manifest  # noqa: E402

SECOND_FIXTURE = "caminandes-gran-dillama-1080p"


def test_alpha_has_two_distinct_high_quality_open_films_with_matching_runtime_pin() -> None:
    registry = load_manifest()
    bunny = registry.fixture("bbb-4k-30-normal")
    second = registry.fixture(SECOND_FIXTURE)
    assert bunny["metadata"]["height"] == 2160
    assert second["metadata"]["height"] == 1080
    assert second["metadata"]["width"] == 1920
    assert bunny["source_url"] != second["source_url"]
    assert bunny["sha256"] != second["sha256"]
    assert second["license"] == "Creative Commons Attribution 4.0"
    assert second["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert second["source_page"] == "https://studio.blender.org/projects/api/assets/2363/"
    assert second["course_content"] is False
    assert second["archive_sha256"] == (
        "2e54abfb18dcb0a25d41e7b5d97fd51b226cec58d2fbcad101cf6deecea8c48b"
    )
    assert second["sha256"] == "468e6743c674689a728726bbe4bb4b2a65bd8702a89f021af26a8bb4d450eebd"
    runtime_fixture, runtime_pin = stress_fixtures._load_registry_fixture(SECOND_FIXTURE)
    assert runtime_fixture == second
    assert runtime_pin == registry.manifest_sha256


@pytest.mark.parametrize(
    ("fixture_id", "changes"),
    [
        (
            SECOND_FIXTURE,
            {"source_url": "https://download.blender.org/demo/movies/unapproved.mp4.zip"},
        ),
        (SECOND_FIXTURE, {"source_page": "https://peach.blender.org/about/"}),
        (SECOND_FIXTURE, {"archive_member": "unexpected.mp4"}),
        (
            SECOND_FIXTURE,
            {
                "license": "Creative Commons Attribution 3.0",
                "license_url": "https://creativecommons.org/licenses/by/3.0/",
            },
        ),
        (
            "bbb-4k-30-normal",
            {
                "license": "Creative Commons Attribution 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            },
        ),
    ],
)
def test_enrolling_a_second_film_does_not_allow_cross_source_provenance(
    tmp_path: Path, fixture_id: str, changes: dict[str, str]
) -> None:
    manifest = json.loads((TOOLS / "fixture-manifest.json").read_text(encoding="utf-8"))
    fixture = next(item for item in manifest["fixtures"] if item["id"] == fixture_id)
    fixture.update(changes)
    candidate = tmp_path / "fixture-manifest.json"
    candidate.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FixtureManifestError):
        load_manifest(candidate, allow_test_copy=True)


@pytest.mark.parametrize("incorrect_license", [False, True])
def test_runtime_verifies_second_fixture_bytes_metadata_and_exact_license(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, incorrect_license: bool
) -> None:
    fixture = deepcopy(dict(load_manifest().fixture(SECOND_FIXTURE)))
    monkeypatch.setattr(stress_fixtures, "_CACHE_ROOT_BOUNDARY", tmp_path)
    for path_field, hash_field in [
        ("cache_path", "sha256"),
        ("archive_cache_path", "archive_sha256"),
    ]:
        path = tmp_path / fixture[path_field]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"isolated test bytes for {path_field}".encode()
        path.write_bytes(payload)
        fixture[hash_field] = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        stress_fixtures,
        "_probe",
        lambda _path: {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "24/1",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "146.041667"},
        },
    )
    if incorrect_license:
        fixture.update(
            license="Creative Commons Attribution 3.0",
            license_url="https://creativecommons.org/licenses/by/3.0/",
        )
        with pytest.raises(stress_fixtures.MediaStressFixtureDenied, match="exact approved source"):
            stress_fixtures._verify_registry_fixture(fixture, "a" * 64, cache_root=tmp_path)
    else:
        result = stress_fixtures._verify_registry_fixture(fixture, "a" * 64, cache_root=tmp_path)
        assert result.fixture_id == SECOND_FIXTURE
        assert result.local_path == tmp_path / fixture["cache_path"]
        assert result.test_only is True
        assert result.provider_activation_required is True
        assert result.playback_grant_required is True


@pytest.mark.parametrize("include_audio", [False, True])
def test_hls_render_invokes_bounded_decoder_filter_and_encoder_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, include_audio: bool
) -> None:
    calls: list[tuple[list[str], int]] = []

    def capture(command: list[str], *, timeout_seconds: int) -> None:
        calls.append((command, timeout_seconds))

    monkeypatch.setattr(hls, "_ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(hls, "_run_ffmpeg", capture)
    profile: dict[str, Any] = dict(load_manifest().rendition_profiles[2])
    source = tmp_path / "approved.mp4"
    command = hls._render_profile(
        source,
        profile,
        tmp_path / "rendered",
        include_audio=include_audio,
        segment_duration=4,
        duration_seconds=12,
        timeout_seconds=120,
    )
    assert calls == [(command, 120)]
    input_index = command.index("-i")
    thread_indices = [index for index, argument in enumerate(command) if argument == "-threads"]
    assert len(thread_indices) == 2
    assert thread_indices[0] < input_index < thread_indices[1]
    assert [command[index + 1] for index in thread_indices] == ["2", "2"]
    for flag in ("-filter_threads", "-filter_complex_threads"):
        assert command.count(flag) == 1
        assert command[command.index(flag) + 1] == "2"
    assert command[input_index + 1] == str(source)
    assert command[command.index("-t") + 1] == "12.000"
    assert ("-c:a" in command) is include_audio
