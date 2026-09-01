from __future__ import annotations

from typing import Any

from ac_platform.http import serve


def test_http_runner_uses_package_app_and_compatible_loop(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **options: object) -> None:
        captured["app"] = app
        captured.update(options)

    monkeypatch.setattr(serve.uvicorn, "run", fake_run)

    assert serve.main(["--host", "127.0.0.1", "--port", "8123", "--reload"]) == 0
    assert captured == {
        "app": "ac_platform.http.app:app",
        "host": "127.0.0.1",
        "port": 8123,
        "reload": True,
        "loop": "ac_platform.application.asyncio_runtime:compatible_event_loop_factory",
    }
