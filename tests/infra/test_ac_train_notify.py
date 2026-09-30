"""Tests for the release train notification spool."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "infra" / "release" / "ac_train_notify.py"
SPEC = importlib.util.spec_from_file_location("ac_train_notify", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
NOTIFY = importlib.util.module_from_spec(SPEC)
sys.modules["ac_train_notify"] = NOTIFY
SPEC.loader.exec_module(NOTIFY)


def test_emit_writes_atomic_private_event_with_hashed_key(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, Path]] = []
    replace = os.replace

    def record_replace(source, destination) -> None:
        source_path, destination_path = Path(source), Path(destination)
        assert source_path.parent == destination_path.parent == tmp_path
        assert source_path.name.endswith(".tmp")
        calls.append((source_path, destination_path))
        replace(source, destination)

    monkeypatch.setattr(NOTIFY.os, "replace", record_replace)
    path = NOTIFY.emit(
        "alert", "lag:staging:web:" + "a" * 40, "staging web is behind", spool=tmp_path, lag=1900
    )

    assert path is not None
    digest = hashlib.sha256(("lag:staging:web:" + "a" * 40).encode()).hexdigest()[:12]
    assert re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z-alert-" + digest + r"\.json", path.name)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(calls) == 1 and calls[0][1] == path
    assert not calls[0][0].exists()
    assert list(tmp_path.glob("*.tmp")) == []
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["kind"] == "alert"
    assert event["key"] == "lag:staging:web:" + "a" * 40
    assert event["text"] == "staging web is behind"
    assert event["fields"] == {"lag": 1900}


def test_emit_deduplicates_unconsumed_keys_and_allows_consumed_keys(tmp_path: Path) -> None:
    first = NOTIFY.emit("review", "review:build-1", "review requested", spool=tmp_path)
    assert first is not None
    assert NOTIFY.emit("alert", "review:build-1", "another event", spool=tmp_path) is None

    event = json.loads(first.read_text(encoding="utf-8"))
    event["consumed"] = True
    first.write_text(json.dumps(event), encoding="utf-8")
    second = NOTIFY.emit("review", "review:build-1", "review requested again", spool=tmp_path)
    assert second is not None and second != first
    assert len(list(tmp_path.glob("*.json"))) == 2


@pytest.mark.parametrize(
    "text",
    [
        "see https://operator:password@example.test/status",
        "token ghp_" + "a" * 36,
    ],
)
def test_emit_refuses_credentials_and_token_patterns(tmp_path: Path, text: str) -> None:
    with pytest.raises(NOTIFY.NotifyError, match="refusing event"):
        NOTIFY.emit("alert", "safe-key", text, spool=tmp_path)
    assert list(tmp_path.glob("*.json")) == []


def test_emit_caps_utf8_text_at_two_kibibytes(tmp_path: Path) -> None:
    path = NOTIFY.emit("alert", "large", "é" * 2000, spool=tmp_path)
    assert path is not None
    text = json.loads(path.read_text(encoding="utf-8"))["text"]
    assert len(text.encode("utf-8")) <= 2048


def test_status_text_uses_shared_format_and_rejects_invalid_status(tmp_path: Path) -> None:
    formatted = NOTIFY.format_status_text("a" * 40, "b" * 40, "c" * 40, True)
    assert formatted == "dev aaaaaaa · staging bbbbbbb · prod ccccccc · smoke ✅"
    path = NOTIFY.emit("status", "status:release-1", formatted, spool=tmp_path)
    assert path is not None
    with pytest.raises(NOTIFY.NotifyError, match="status text"):
        NOTIFY.emit("status", "bad-status", "staging is green", spool=tmp_path)


def test_cli_accepts_fields_and_spool_override(tmp_path: Path, capsys) -> None:
    result = NOTIFY.main(
        [
            "alert",
            "--key",
            "state:staging:paused",
            "--text",
            "staging paused",
            "--field",
            "env=staging",
            "--spool",
            str(tmp_path),
        ]
    )
    assert result == 0
    output = capsys.readouterr().out.strip()
    event = json.loads(Path(output).read_text(encoding="utf-8"))
    assert event["fields"] == {"env": "staging"}
