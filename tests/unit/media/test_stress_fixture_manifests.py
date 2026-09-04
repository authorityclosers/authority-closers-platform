from __future__ import annotations

import hashlib
import json
import sys
import warnings
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools" / "media-player-stress"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_hls_ladder as hls  # noqa: E402
from fixture_harness import (  # noqa: E402
    _ALLOWED_DOWNLOAD_HOSTS,
    FixtureHarnessError,
    FixtureManifestError,
    _validate_url,
    _validate_zip_archive,
    canonicalize_cache_root,
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
