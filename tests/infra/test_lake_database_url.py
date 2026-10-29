"""The production lake export's database address helper (owner approval 29 Oct 2026)."""

from __future__ import annotations

import os
import runpy
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra/application/scripts/ac-lake-database-url"
DROP_IN = (
    Path(__file__).resolve().parents[2]
    / "infra/application/systemd/ac-lake-export@production.service.d/50-database-url.conf"
)


def load() -> dict:
    return runpy.run_path(str(SCRIPT))


def test_rewrites_only_the_host_and_keeps_credentials_and_database() -> None:
    rewrite = load()["rewrite"]
    url = "postgresql+psycopg://runtime:p%40ss@postgres/ac_platform?sslmode=disable"
    assert (
        rewrite(url, "172.24.0.2")
        == "postgresql+psycopg://runtime:p%40ss@172.24.0.2/ac_platform?sslmode=disable"
    )
    assert (
        rewrite("postgresql://u:x@postgres:6432/db", "10.0.0.9")
        == "postgresql://u:x@10.0.0.9:6432/db"
    )


@pytest.mark.parametrize(
    ("url", "address"),
    [("postgresql://u:x@db.example.test/db", "172.24.0.2"), ("postgresql://u:x@postgres/db", "")],
)
def test_refuses_an_unexpected_host_or_missing_address(url: str, address: str) -> None:
    with pytest.raises(ValueError):
        load()["rewrite"](url, address)


def test_writes_a_private_file_and_prints_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    namespace = load()
    configured = "postgresql+psycopg://runtime:fictional-secret@postgres/ac_platform"

    def inspect(name: str) -> dict:
        if name.endswith("-api-1"):
            return {"Config": {"Env": ["PATH=/usr/bin", f"AC_DATABASE_URL={configured}"]}}
        return {
            "NetworkSettings": {
                "Networks": {"ac-application-production_data": {"IPAddress": "172.24.0.2"}}
            }
        }

    namespace["main"].__globals__["inspect"] = inspect
    output = tmp_path / "database-url"
    assert namespace["main"](["production", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == configured.replace("@postgres/", "@172.24.0.2/")
    assert stat.S_IMODE(os.stat(output).st_mode) == 0o600
    captured = capsys.readouterr()
    assert "fictional-secret" not in captured.out + captured.err


def test_unknown_environment_and_failures_write_nothing(tmp_path: Path) -> None:
    namespace = load()
    output = tmp_path / "database-url"
    assert namespace["main"](["staging", str(output)]) == 2

    def broken(name: str) -> dict:
        raise RuntimeError("docker unavailable")

    namespace["main"].__globals__["inspect"] = broken
    assert namespace["main"](["production", str(output)]) == 1
    assert not output.exists()


def test_drop_in_builds_the_address_privately_before_the_export() -> None:
    text = DROP_IN.read_text(encoding="utf-8")
    assert "RuntimeDirectory=ac-lake-export-production" in text
    assert "RuntimeDirectoryMode=0700" in text
    assert (
        "ExecStartPre=+/usr/local/sbin/ac-lake-database-url production "
        "/run/ac-lake-export-production/database-url" in text
    )
