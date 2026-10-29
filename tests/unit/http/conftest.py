"""HTTP tests use a disposable durable intake mount, never the host journal."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def telemetry_journal_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AC_TELEMETRY_SPOOL_ROOT", str(tmp_path / "telemetry"))
