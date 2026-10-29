from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.audio_bakeoff import engine, worker
from ac_platform.conversation_intelligence.signals import SignalError


def test_overlap_and_same_speaker_union_do_not_double_count():
    turns = [
        {"start_ms": 0, "end_ms": 2000, "speaker_id": "a"},
        {"start_ms": 1000, "end_ms": 3000, "speaker_id": "a"},
        {"start_ms": 2500, "end_ms": 4000, "speaker_id": "b"},
        {"start_ms": 4500, "end_ms": 5000, "speaker_id": "a"},
    ]
    result = engine.summarize(turns, 6000)
    assert result["speech_ms"] == 4500
    assert result["silence_ms"] == 1500
    assert result["overlap_ms"] == 500
    assert result["speaker_talk_ms"] == {"a": 3500, "b": 1500}
    assert result["speaker_talk_share"] == {"a": 0.7, "b": 0.3}
    assert result["nonoverlapping_response_gaps_ms"] == [500]
    assert result["longest_contiguous_turn_ms"] == 3000
    assert result["interruptions"] == "not_inferred_from_overlap"


@pytest.mark.parametrize("end", [float("nan"), float("inf"), -1, 7000, True])
def test_invalid_model_times_fail_closed(end):
    with pytest.raises(SignalError):
        engine.summarize([{"start_ms": 0, "end_ms": end, "speaker_id": "a"}], 6000)


def test_silence_and_speaker_limit():
    assert engine.summarize([], 1000)["speaker_talk_share"] == {}
    with pytest.raises(SignalError, match="speaker_limit"):
        engine.summarize(
            [{"start_ms": 0, "end_ms": 1, "speaker_id": sp} for sp in ["a", "b", "c"]], 1000
        )


def test_missing_and_tampered_models_rejected_before_optional_imports(tmp_path):
    with pytest.raises(SignalError, match="artifact_mismatch"):
        engine.analyze(Path("unused.wav"), tmp_path)
    for name in engine.ARTIFACTS:
        (tmp_path / name).write_bytes(b"wrong weights")
    with pytest.raises(SignalError, match="artifact_mismatch"):
        engine.verify_artifacts(tmp_path)


def test_disabled_path_is_exact_audioatlas_result(monkeypatch, tmp_path):
    expected = {"existing": "canonical result"}
    monkeypatch.setattr(worker, "inspect_media", lambda *a, **kw: expected)
    monkeypatch.setattr(worker, "_run_bounded", lambda *a, **kw: pytest.fail("must not run"))
    assert (
        worker.inspect_with_local_audio(Path("unused"), tmp_path, model_root=tmp_path) is expected
    )
    assert not list(tmp_path.iterdir())


def test_optional_failure_retains_audioatlas(monkeypatch, tmp_path):
    expected = {"media_duration_ms": 601000}
    monkeypatch.setattr(worker, "inspect_media", lambda *a, **kw: expected)
    assert (
        worker.inspect_with_local_audio(Path("unused"), tmp_path, model_root=tmp_path, enabled=True)
        is expected
    )
    assert "audioatlas_fallback" in (tmp_path / "local-audio-experiment-status.json").read_text()


@pytest.mark.parametrize("payload", [b"[]", b'{"schema":"wrong"}', b"not-json"])
def test_invalid_helper_result_keeps_canonical_checkpoint(monkeypatch, tmp_path, payload):
    expected = {"media_duration_ms": 1000, "source_sha256": "a" * 64}
    output = tmp_path / "result"
    output.mkdir()
    monkeypatch.setattr(worker, "inspect_media", lambda *a, **kw: expected)
    monkeypatch.setattr(worker.shutil, "which", lambda *a: "/usr/bin/ffmpeg")
    monkeypatch.setattr(worker, "file_sha256", lambda *a: "a" * 64)
    monkeypatch.setattr(worker, "_run_bounded", lambda *a, **kw: payload)
    assert (
        worker.inspect_with_local_audio(Path("unused"), output, model_root=tmp_path, enabled=True)
        is expected
    )
    assert not (output / "local-audio-experiment.json").exists()
    assert (output / "local-audio-experiment-status.json").exists()


def test_unwritable_optional_status_does_not_break_audioatlas(monkeypatch, tmp_path):
    expected = {"media_duration_ms": 601000}
    monkeypatch.setattr(worker, "inspect_media", lambda *a, **kw: expected)

    def full_disk(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", full_disk)
    assert (
        worker.inspect_with_local_audio(Path("unused"), tmp_path, model_root=tmp_path, enabled=True)
        is expected
    )
