from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools" / "media-player-stress"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import prepare_full_film_release as release  # noqa: E402
from fixture_harness import FixtureHarnessError  # noqa: E402


def test_2160p_outputs_copy_video_and_normalize_one_aac_track(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    progressive = release.progressive_command("ffmpeg", source, tmp_path / "progressive.mp4")
    playlist = tmp_path / "2160p" / "index.m3u8"
    hls = release.hls_copy_command("ffmpeg", source, playlist)
    for command in (progressive, hls):
        assert command[command.index("-c:v") + 1] == "copy"
        assert command[command.index("-c:a") + 1] == "aac"
        assert command[command.index("-map", command.index("-map") + 1) + 1] == "0:a:0"
        assert "-vf" not in command
        assert "http://" not in " ".join(command)
        assert "https://" not in " ".join(command)
    assert hls[hls.index("-hls_segment_filename") + 1] == str(
        tmp_path / "2160p" / "segment-%05d.ts"
    )


def test_lower_rendition_is_bounded_and_uses_source_keyframes(tmp_path: Path) -> None:
    command = release.hls_lower_command(
        "ffmpeg", tmp_path / "source.mp4", tmp_path / "720p" / "index.m3u8"
    )
    assert command[command.index("-vf") + 1] == "scale=1280:720:flags=lanczos,format=yuv420p"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-threads", command.index("-c:v")) + 1] == "2"
    assert command[command.index("-filter_threads") + 1] == "2"
    assert command[command.index("-filter_complex_threads") + 1] == "2"
    assert command[command.index("-force_key_frames") + 1] == "source"
    assert command[command.index("-fps_mode") + 1] == "passthrough"
    assert command[command.index("-sc_threshold") + 1] == "0"
    assert command[command.index("-maxrate") + 1] == "3080k"


@pytest.mark.parametrize("timeout", [True, 299, 7201])
def test_total_timeout_is_bounded_before_source_or_ffmpeg_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, timeout: int
) -> None:
    monkeypatch.setattr(release, "load_manifest", lambda: object())
    with pytest.raises(FixtureHarnessError, match="five minutes and two hours"):
        release.prepare_release_pack(
            object(), cache_root=tmp_path, output=tmp_path / "out", timeout_seconds=timeout
        )


def test_source_validation_rejects_non_4k_or_non_h264() -> None:
    with pytest.raises(FixtureHarnessError, match="compatible 2160p H.264"):
        release._require_source(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                    },
                    {"codec_type": "audio", "codec_name": "mp3"},
                ]
            }
        )


def test_playlist_inventory_rejects_external_or_unbounded_entries(tmp_path: Path) -> None:
    playlist = tmp_path / "index.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-INDEPENDENT-SEGMENTS\n#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXTINF:4.0,\nhttps://example.test/segment.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    with pytest.raises(FixtureHarnessError, match="unsafe segment entry"):
        release._playlist_inventory(playlist, stage_root=tmp_path)


def test_switch_points_must_match() -> None:
    release._assert_aligned([4.0, 4.0, 2.6], [4.0, 4.0, 2.6])
    with pytest.raises(FixtureHarnessError, match="switch points"):
        release._assert_aligned([4.0, 4.0, 2.6], [4.0, 4.2, 2.4])


def test_file_inventory_is_sorted_hashed_and_excludes_its_manifest(tmp_path: Path) -> None:
    (tmp_path / "z.ts").write_bytes(b"z")
    (tmp_path / "a.ts").write_bytes(b"a")
    (tmp_path / "release-manifest.json").write_text("self", encoding="utf-8")
    inventory = release._file_inventory(tmp_path)
    assert [item["path"] for item in inventory] == ["a.ts", "z.ts"]
    assert all(len(str(item["sha256"])) == 64 for item in inventory)
