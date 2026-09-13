"""Narrow operator CLI composition and failure-boundary checks."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from ac_platform.catalog import cli


def test_promote_uses_validated_studio_service_graph(monkeypatch) -> None:
    service = object()
    validated = []
    runtime = SimpleNamespace(
        studio_video_runtime=SimpleNamespace(
            service=service,
            validate=lambda: validated.append(True),
        ),
    )
    monkeypatch.setattr(cli, "create_default_media_runtime", lambda _settings: runtime)

    assert cli._configured_studio_service(object()) is service
    assert validated == [True]


def test_promote_refuses_missing_studio_filesystem_graph(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "create_default_media_runtime",
        lambda _settings: SimpleNamespace(studio_video_runtime=None),
    )

    try:
        cli._configured_studio_service(object())
    except cli.FreeCourseCliError as error:
        assert str(error) == "the configured Studio filesystem runtime is unavailable"
    else:  # pragma: no cover - assertion makes the refusal contract explicit
        raise AssertionError("missing Studio runtime was accepted")


def test_main_does_not_echo_secret_from_value_error(monkeypatch, capsys) -> None:
    canary = "session-secret-canary"

    def fail(coroutine):
        coroutine.close()
        raise ValueError(f"invalid settings: {canary}")

    monkeypatch.setattr(cli, "run_async", fail)
    result = cli.main(
        [
            "publish",
            "--environment",
            "test",
            "--source-program-id",
            str(uuid4()),
            "--public-tenant-id",
            str(uuid4()),
            "--command-id",
            str(uuid4()),
            "--reason",
            "test",
        ]
    )

    assert result == 2
    captured = capsys.readouterr()
    assert canary not in captured.err
    assert captured.err == (
        "free-course command refused: invalid or unavailable command input\n"
    )
