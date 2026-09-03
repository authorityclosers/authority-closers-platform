from __future__ import annotations

from typing import Any

from ac_platform.application import asyncio_runtime


async def _value() -> int:
    return 42


def test_windows_entrypoints_use_a_selector_loop(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, *, loop_factory: object) -> None:
            captured["loop_factory"] = loop_factory

        def __enter__(self) -> FakeRunner:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def run(self, coroutine: Any) -> int:
            coroutine.close()
            return 42

    monkeypatch.setattr(asyncio_runtime.sys, "platform", "win32")
    monkeypatch.setattr(asyncio_runtime.asyncio, "Runner", FakeRunner)

    assert asyncio_runtime.run_async(_value()) == 42
    assert captured["loop_factory"] is asyncio_runtime.compatible_event_loop_factory


def test_windows_loop_factory_returns_a_selector_loop(monkeypatch: Any) -> None:
    sentinel = object()
    monkeypatch.setattr(asyncio_runtime.sys, "platform", "win32")
    monkeypatch.setattr(
        asyncio_runtime.asyncio,
        "SelectorEventLoop",
        lambda: sentinel,
    )

    assert asyncio_runtime.compatible_event_loop_factory() is sentinel


def test_non_windows_loop_factory_returns_the_platform_default(monkeypatch: Any) -> None:
    sentinel = object()
    monkeypatch.setattr(asyncio_runtime.sys, "platform", "linux")
    monkeypatch.setattr(asyncio_runtime.asyncio, "new_event_loop", lambda: sentinel)

    assert asyncio_runtime.compatible_event_loop_factory() is sentinel


def test_non_windows_entrypoints_keep_the_standard_runner(monkeypatch: Any) -> None:
    def fake_run(coroutine: Any) -> int:
        coroutine.close()
        return 42

    monkeypatch.setattr(asyncio_runtime.sys, "platform", "linux")
    monkeypatch.setattr(asyncio_runtime.asyncio, "run", fake_run)

    assert asyncio_runtime.run_async(_value()) == 42
