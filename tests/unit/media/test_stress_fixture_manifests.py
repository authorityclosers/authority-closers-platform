from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
import warnings
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools" / "media-player-stress"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_hls_ladder as hls  # noqa: E402
import fixture_harness as harness  # noqa: E402
from fixture_harness import (  # noqa: E402
    _ALLOWED_DOWNLOAD_HOSTS,
    EXPECTED_CAPTIONS_MANIFEST_SHA256,
    EXPECTED_FIXTURE_MANIFEST_SHA256,
    EXPECTED_NETWORK_SCENARIOS_SHA256,
    EXPECTED_TEST_MANIFEST_SHA256,
    FixtureHarnessError,
    FixtureManifestError,
    _AllowlistedRedirectHandler,
    _stream_response_to_file,
    _validate_url,
    _validate_zip_archive,
    acquire_external_fixture,
    canonicalize_cache_root,
    generate_fixture,
    load_manifest,
    load_network_scenarios,
    load_test_manifest,
)


def _json(name: str) -> dict[str, object]:
    value = json.loads((TOOLS / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_fixture_manifest_is_bounded_and_allowlisted() -> None:
    registry = load_manifest()

    assert registry.manifest_sha256 == EXPECTED_FIXTURE_MANIFEST_SHA256
    assert registry.source_policy["arbitrary_public_urls"] is False
    assert set(registry.source_policy["allowed_download_hosts"]) == {"download.blender.org"}
    assert all(fixture["course_content"] is False for fixture in registry.fixtures.values())
    assert all(
        "source_last_modified" not in fixture
        and fixture.get("source_date_basis")
        == "official Blender download directory listing; not asserted as HTTP Last-Modified"
        for fixture in registry.fixtures.values()
        if fixture["kind"] == "external_open_license"
    )
    assert all(
        str(fixture.get("source_url", "")).startswith("https://download.blender.org/")
        for fixture in registry.fixtures.values()
        if fixture["kind"] == "external_open_license"
    )
    assert [profile["id"] for profile in registry.rendition_profiles] == [
        "2160p",
        "1440p",
        "1080p",
        "720p",
        "480p",
        "360p",
    ]


def test_fixture_manifest_rejects_an_unlisted_download_host(tmp_path: Path) -> None:
    mutated = deepcopy(_json("fixture-manifest.json"))
    mutated_fixtures = mutated["fixtures"]
    assert isinstance(mutated_fixtures, list)
    mutated_fixtures[0]["source_url"] = "https://example.test/fixture.zip"
    path = tmp_path / "fixture-manifest.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    with pytest.raises(FixtureManifestError, match="approved HTTPS URL"):
        load_manifest(path, allow_test_copy=True)


def test_manifest_path_and_nonstandard_https_port_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(FixtureManifestError, match="exact-path"):
        load_manifest(tmp_path / "fixture-manifest.json")
    with pytest.raises(FixtureManifestError, match="must not contain '..'"):
        load_manifest(TOOLS / ".." / "media-player-stress" / "fixture-manifest.json")
    with pytest.raises(FixtureManifestError, match="approved HTTPS URL"):
        _validate_url(
            "https://download.blender.org:8443/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip",
            field_name="source_url",
            allowed_hosts=_ALLOWED_DOWNLOAD_HOSTS,
        )


def test_all_checked_in_manifest_authorities_have_pinned_digests() -> None:
    assert hashlib.sha256((TOOLS / "fixture-manifest.json").read_bytes()).hexdigest() == (
        EXPECTED_FIXTURE_MANIFEST_SHA256
    )
    assert hashlib.sha256((TOOLS / "captions-manifest.json").read_bytes()).hexdigest() == (
        EXPECTED_CAPTIONS_MANIFEST_SHA256
    )
    assert hashlib.sha256((TOOLS / "network-scenarios.json").read_bytes()).hexdigest() == (
        EXPECTED_NETWORK_SCENARIOS_SHA256
    )
    assert hashlib.sha256((TOOLS / "test-manifest.json").read_bytes()).hexdigest() == (
        EXPECTED_TEST_MANIFEST_SHA256
    )


def test_generated_ffmpeg_args_are_an_exact_allowlist(tmp_path: Path) -> None:
    mutated = deepcopy(_json("fixture-manifest.json"))
    fixtures = mutated["fixtures"]
    assert isinstance(fixtures, list)
    generated = next(item for item in fixtures if item["kind"] == "generated_lavfi")
    args = generated["ffmpeg_args"]
    assert isinstance(args, list)
    args.extend(["-vf", "drawtext=textfile=/outside/secret.txt"])
    path = tmp_path / "fixture-manifest.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    with pytest.raises(FixtureManifestError, match="exact approved lavfi allowlist"):
        load_manifest(path, allow_test_copy=True)


def test_redirect_target_is_rejected_before_urllib_can_contact_it() -> None:
    handler = _AllowlistedRedirectHandler(
        expected_path="/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip"
    )
    request = urllib.request.Request(
        "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip"
    )

    with pytest.raises(FixtureHarnessError, match="redirected outside"):
        handler.redirect_request(
            request,
            object(),
            302,
            "found",
            {},
            "https://127.0.0.1/fixture.zip",
        )


def test_invalid_fixture_timeouts_are_bounded_harness_errors() -> None:
    registry = load_manifest()
    with pytest.raises(FixtureHarnessError, match="timeout_seconds"):
        acquire_external_fixture(registry, "bbb-320x180-24", timeout_seconds=1)
    with pytest.raises(FixtureHarnessError, match="timeout_seconds"):
        generate_fixture(registry, "generated-16x9-4s", timeout_seconds=1)


def test_download_stream_enforces_wall_clock_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Clock:
        values = iter((100.0, 100.0, 101.0))

        def monotonic(self) -> float:
            return next(self.values)

    class _Response:
        def read(self, _size: int) -> bytes:
            return b"fixture bytes"

    monkeypatch.setattr(harness.time, "monotonic", _Clock().monotonic)
    partial = tmp_path / "archive.part"

    with pytest.raises(FixtureHarnessError, match="exceeded its deadline"):
        _stream_response_to_file(
            _Response(),
            partial,
            deadline=100.5,
            max_bytes=1024,
        )

    assert partial.read_bytes() == b"fixture bytes"


def test_cli_cache_root_is_bounded_to_the_ignored_repository_boundary(tmp_path: Path) -> None:
    boundary = TOOLS / ".artifacts"
    assert canonicalize_cache_root(boundary / "hls") == (boundary / "hls").resolve()
    with pytest.raises(FixtureHarnessError, match="must not contain '..'"):
        canonicalize_cache_root(boundary / ".." / "escape")
    with pytest.raises(FixtureHarnessError, match="ignored"):
        canonicalize_cache_root(tmp_path / "outside")


def test_zip_validation_rejects_duplicate_names_and_bomb_ratios(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("fixture.mp4", b"one")
            archive.writestr("fixture.mp4", b"two")
    with (
        zipfile.ZipFile(duplicate) as archive,
        pytest.raises(FixtureHarnessError, match="duplicate"),
    ):
        _validate_zip_archive(archive, max_uncompressed_bytes=1024)

    bomb = tmp_path / "ratio.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("fixture.mp4", b"A" * 1024 * 1024)
    with (
        zipfile.ZipFile(bomb) as archive,
        pytest.raises(FixtureHarnessError, match="compression ratio"),
    ):
        _validate_zip_archive(archive, max_uncompressed_bytes=2 * 1024 * 1024)


def test_caption_manifest_matches_synthetic_webvtt_bytes() -> None:
    manifest = _json("captions-manifest.json")
    caption_path = TOOLS / str(manifest["path"])

    assert manifest["status"] == "test_only"
    assert manifest["course_content"] is False
    assert manifest["source_kind"] == "synthetic"
    assert hashlib.sha256(caption_path.read_bytes()).hexdigest() == manifest["sha256"]


def test_webvtt_runtime_parser_rejects_overlap_and_bad_timing(tmp_path: Path) -> None:
    path = tmp_path / "bad.vtt"
    path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nfirst\n\n00:00:01.000 --> 00:00:03.000\nsecond\n",
        encoding="utf-8",
    )
    with pytest.raises(FixtureHarnessError, match="overlap"):
        hls._parse_webvtt(path)


def test_hls_playlist_rejects_discontinuities_and_unbounded_target_duration(
    tmp_path: Path,
) -> None:
    segment = tmp_path / "segment-00000.ts"
    segment.write_bytes(b"ts")
    playlist = tmp_path / "index.m3u8"
    playlist.write_text(
        "\n".join(
            [
                "#EXTM3U",
                "#EXT-X-TARGETDURATION:5",
                "#EXT-X-MEDIA-SEQUENCE:0",
                "#EXT-X-PLAYLIST-TYPE:VOD",
                "#EXT-X-INDEPENDENT-SEGMENTS",
                "#EXT-X-DISCONTINUITY",
                "#EXTINF:4.000,",
                "segment-00000.ts",
                "#EXT-X-ENDLIST",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(FixtureHarnessError, match="missing required terminators"):
        hls._playlist_segments(playlist, stage_root=tmp_path, segment_duration=4)

    playlist.write_text(
        playlist.read_text(encoding="utf-8").replace("#EXT-X-DISCONTINUITY\n", ""),
        encoding="utf-8",
    )
    with pytest.raises(FixtureHarnessError, match="target duration"):
        hls._playlist_segments(playlist, stage_root=tmp_path, segment_duration=4)


def test_network_and_test_manifests_cover_the_same_checked_in_ids() -> None:
    fixture_manifest = load_manifest()
    network = _json("network-scenarios.json")
    test_manifest = _json("test-manifest.json")
    validated_scenarios = load_network_scenarios()
    load_test_manifest(fixture_manifest)
    scenarios = network["scenarios"]
    assert isinstance(scenarios, list)
    scenario_ids = [scenario["id"] for scenario in scenarios]
    assert len(scenario_ids) == len(set(scenario_ids))
    assert set(scenario_ids) == set(test_manifest["network_scenario_ids"])
    assert set(fixture_manifest.fixtures) == set(test_manifest["fixture_ids"])
    assert test_manifest["course_content"] is False
    assert all(
        isinstance(scenario["latency_ms"], int) and scenario["latency_ms"] >= 0
        for scenario in scenarios
    )
    assert [scenario["id"] for scenario in validated_scenarios] == scenario_ids
    assert all(
        scenario["range_requests"] in {"allowed", "denied", "unknown"} for scenario in scenarios
    )
    assert all(
        scenario["expected_state"]
        in {"playing", "buffering", "error", "recovering", "authorization_error", "provider_error"}
        for scenario in scenarios
    )
    assert all(
        isinstance(scenario["packet_loss_percent"], (int, float))
        and 0 <= scenario["packet_loss_percent"] <= 100
        for scenario in scenarios
    )
