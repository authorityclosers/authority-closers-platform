from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from ac_platform.application import release_identity

SCRIPT = Path(__file__).parents[3] / "scripts" / "seed_staging.py"
SPEC = spec_from_file_location("seed_staging", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
main = MODULE.main


def _write_release_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_id: str,
) -> None:
    marker = tmp_path / ".ac-release-id"
    marker.write_text(f"{release_id}\n", encoding="ascii")
    monkeypatch.setattr(release_identity, "BAKED_RELEASE_ID_PATH", marker)


def test_cli_refuses_production_before_database_initialization(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "--environment",
            "production",
            "--seed-data",
            "does-not-exist.json",
            "--actor-person-id",
            "00000000-0000-0000-0000-000000000001",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "production is never an allowed target" in captured.err
    assert captured.out == ""


def test_cli_requires_staging_environment_for_technical_validation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AC_ENVIRONMENT", raising=False)
    result = main(
        [
            "--technical-validation",
            "--acknowledge-staging-technical-validation",
            "--release-id",
            "0123456789abcdef0123456789abcdef01234567",
            "--actor-person-id",
            "00000000-0000-0000-0000-000000000001",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "AC_ENVIRONMENT=staging is required" in captured.err
    assert captured.out == ""


def test_cli_requires_explicit_technical_validation_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release_id = "0123456789abcdef0123456789abcdef01234567"
    _write_release_marker(tmp_path, monkeypatch, release_id)
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_RELEASE_ID", release_id)
    result = main(
        [
            "--technical-validation",
            "--release-id",
            release_id,
            "--actor-person-id",
            "00000000-0000-0000-0000-000000000001",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "acknowledge-staging-technical-validation" in captured.err
    assert captured.out == ""


def test_cli_requires_runtime_release_binding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.delenv("AC_RELEASE_ID", raising=False)
    result = main(
        [
            "--technical-validation",
            "--acknowledge-staging-technical-validation",
            "--actor-person-id",
            "00000000-0000-0000-0000-000000000001",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "AC_RELEASE_ID is required" in captured.err
    assert captured.out == ""


def test_cli_rejects_release_override_that_differs_from_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_RELEASE_ID", "a" * 40)
    result = main(
        [
            "--technical-validation",
            "--acknowledge-staging-technical-validation",
            "--release-id",
            "b" * 40,
            "--actor-person-id",
            "00000000-0000-0000-0000-000000000001",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "must match AC_RELEASE_ID" in captured.err
    assert captured.out == ""


def test_cli_rejects_matching_fabricated_environment_and_argument_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_release_marker(tmp_path, monkeypatch, "a" * 40)
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_RELEASE_ID", "b" * 40)

    result = main(
        [
            "--technical-validation",
            "--acknowledge-staging-technical-validation",
            "--release-id",
            "b" * 40,
            "--actor-person-id",
            "00000000-0000-0000-0000-000000000001",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "AC_RELEASE_ID does not match the baked API release marker" in captured.err
    assert captured.out == ""
