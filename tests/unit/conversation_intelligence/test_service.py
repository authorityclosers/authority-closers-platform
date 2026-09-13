"""Hosted service supervision and isolation; all payloads/identities are synthetic."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ac_platform.conversation_intelligence import service
from ac_platform.conversation_intelligence.service_config import (
    WorkerServiceConfig,
    load_service_config,
)

from .test_service_config import manifest, write_config


@pytest.mark.parametrize(
    "name",
    [
        "AC_DATABASE_URL",
        "AC_SESSION_TOKEN_PEPPER",
        "GROQ_API_KEY",
        "INFISICAL_TOKEN",
        "PYTHONPATH",
        "HTTP_PROXY",
        "LD_PRELOAD",
    ],
)
def test_worker_refuses_inherited_application_or_provider_environment(name: str) -> None:
    with pytest.raises(ValueError, match="^worker_environment_not_isolated$"):
        service.validate_service_environment({"PATH": "/usr/bin", name: "synthetic"})
    service.validate_service_environment({"PATH": "/usr/bin", "PYTHON_VERSION": "3.13"})


def test_check_only_never_reads_credentials_or_starts_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = manifest(tmp_path)
    path, digest = write_config(tmp_path, value)
    marker = tmp_path / "release"
    marker.write_text(value["release_id"])
    marker.chmod(0o444)
    monkeypatch.setattr(service, "_INSTALLED_RELEASE", marker)

    def unexpected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("check-only command started execution or read a credential")

    monkeypatch.setattr(service, "load_database_url", unexpected)
    monkeypatch.setattr(service.asyncio, "run", unexpected)
    assert service.main(["--config", str(path), "--sha256", digest, "--check"]) == 0
    assert capsys.readouterr().out == "worker_config_valid\n"


def test_prepare_initializes_and_rechecks_owned_roots_without_reading_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = manifest(tmp_path)
    path, digest = write_config(tmp_path, value)
    marker = tmp_path / "release"
    marker.write_text(value["release_id"])
    marker.chmod(0o444)
    monkeypatch.setattr(service, "_INSTALLED_RELEASE", marker)
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service, "validate_service_environment", lambda env: None)
    monkeypatch.setattr(service.os, "umask", lambda mask: None)

    def unexpected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("storage preparation started execution or read a credential")

    monkeypatch.setattr(service, "load_database_url", unexpected)
    monkeypatch.setattr(service.asyncio, "run", unexpected)
    command = ["--config", str(path), "--sha256", digest, "--prepare-storage"]
    assert service.main(command) == 0
    assert service.main(command) == 0
    for key in ("sales_xray_storage_root", "sales_xray_scratch_root"):
        assert (Path(value[key]) / ".ac-recording-storage").is_file()
    assert capsys.readouterr().out == "worker_storage_prepared\nworker_storage_prepared\n"


@pytest.mark.parametrize("failure", [False, True])
async def test_shutdown_disposes_engine_and_stops_new_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    config = load_service_config(*write_config(tmp_path, manifest(tmp_path)))
    stop = asyncio.Event()
    calls: list[str] = []
    engine_options: dict[str, Any] = {}

    class Engine:
        async def dispose(self) -> None:
            calls.append("disposed")

    engine = Engine()

    def create_engine(*args: Any, **kwargs: Any) -> Engine:
        engine_options.update(kwargs)
        return engine

    class Retention:
        async def step(self) -> bool:
            calls.append("retention")
            stop.set()
            if failure:
                raise RuntimeError("synthetic-worker-failure")
            return True

    class MustNotRun:
        async def run_once(self) -> bool:
            pytest.fail("work admitted after stop")

        async def step(self) -> bool:
            pytest.fail("work admitted after stop")

    native_module = ModuleType("ac_platform.conversation_intelligence.native_runtime")
    native_module.SocketNativeRuntime = lambda **kwargs: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, native_module.__name__, native_module)
    monkeypatch.setattr(service, "load_database_url", lambda path: "synthetic-dsn")
    monkeypatch.setattr(service, "create_async_engine", create_engine)
    monkeypatch.setattr(service, "async_sessionmaker", lambda *args, **kwargs: object())
    monkeypatch.setattr(service, "PrivateLocalRecordingStorage", lambda *args: object())
    monkeypatch.setattr(service, "HostedConversationWorker", lambda *args, **kwargs: MustNotRun())
    monkeypatch.setattr(
        service,
        "compose_hosted_reporting",
        lambda *args, **kwargs: SimpleNamespace(
            storage=object(), retention=Retention(), plans=MustNotRun(), inference=MustNotRun()
        ),
    )
    if failure:
        with pytest.raises(RuntimeError, match="synthetic-worker-failure"):
            await service.run_service(config, stop)
    else:
        result = await service.run_service(config, stop)
        assert result.retention_work == 1
        assert result.offline_work == result.plan_work == result.inference_work == 0
    assert calls == ["retention", "disposed"]
    assert engine_options["hide_parameters"] is True
    assert engine_options["echo"] is False
    assert engine_options["pool_size"] == 2 and engine_options["max_overflow"] == 0


@pytest.mark.asyncio
async def test_bootstrap_waits_idle_without_database_queue_or_provider_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = manifest(tmp_path)
    value["bootstrap_only"] = True
    value["providers"] = []
    config = load_service_config(*write_config(tmp_path, value))
    stop = asyncio.Event()
    validated: list[WorkerServiceConfig] = []

    monkeypatch.setattr(
        service,
        "validate_bootstrap_configuration",
        lambda received: validated.append(received),
    )
    monkeypatch.setattr(
        service,
        "configured_launchers",
        lambda _config: pytest.fail("bootstrap must not inspect provider identities"),
    )
    monkeypatch.setattr(
        service,
        "create_async_engine",
        lambda *_args, **_kwargs: pytest.fail("bootstrap must not open the database"),
    )

    task = asyncio.create_task(service.run_service(config, stop))
    await asyncio.sleep(0)
    assert not task.done()
    assert validated == [config]
    stop.set()

    assert await task == service.ConversationWorkerRunnerSummary()


def test_cli_failure_outputs_no_exception_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(*args: Any) -> Any:
        raise ValueError("synthetic-private-payload")

    monkeypatch.setattr(service, "load_service_config", invalid)
    assert service.main(["--config", str(tmp_path / "missing"), "--sha256", "a" * 64]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "worker_service_failed\n"
