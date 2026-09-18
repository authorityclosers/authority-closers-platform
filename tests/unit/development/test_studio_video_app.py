from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import ac_platform.development.studio_video_app as studio_app
from ac_platform.application.settings import Settings
from ac_platform.media.scanner import ScanResult
from ac_platform.media.studio_video_runner import StudioVideoRunnerSummary


def _settings(**updates: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "local",
        "database_url": ("postgresql+psycopg://ac_runtime:unused@127.0.0.1:55432/ac_local_sandbox"),
        "database_migrator_url": (
            "postgresql+psycopg://ac_owner:unused@127.0.0.1:55432/ac_local_sandbox"
        ),
        "external_side_effects_hold": True,
        "email_provider": "fake",
        "media_provider_enabled": False,
        "google_oauth_client_id": None,
        "google_oauth_client_secret": None,
        "session_token_pepper": "local-studio-video-session-pepper-long-enough",  # noqa: S105
        "oauth_transaction_secret": "local-studio-video-oauth-secret-long-enough",  # noqa: S105
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def _proof_model() -> studio_app.LocalStudioVideoScannerReadiness:
    return studio_app.LocalStudioVideoScannerReadiness.model_validate_json(
        json.dumps(_proof()), strict=True
    )


def _proof(*, now: datetime | None = None) -> dict[str, object]:
    current = now or datetime.now(UTC)
    definition = {
        "version": 1,
        "updated_at": (current - timedelta(hours=1)).isoformat(),
        "sha256": "a" * 64,
    }
    return {
        "schema_version": "ac.local-studio-video-scanner-readiness.v1",
        "environment": "local",
        "host": "127.0.0.1",
        "port": 13310,
        "max_source_bytes": 2_000_000_000,
        "stream_max_length": 2_000_000_000,
        "max_file_size": 2_000_000_000,
        "max_scan_size": 4_000_000_000,
        "alert_exceeds_max": True,
        "verified_at": current.isoformat(),
        "expires_at": (current + timedelta(hours=1)).isoformat(),
        "clamd_version": "1.4.2",
        "scanner_image_digest": "sha256:" + "b" * 64,
        "managed_config_sha256": "c" * 64,
        "evidence_sha256": "d" * 64,
        "definitions": {
            "daily": definition,
            "main": {**definition, "version": 2, "sha256": "e" * 64},
            "bytecode": {**definition, "version": 3, "sha256": "f" * 64},
        },
    }


def _write_proof(path: Path, **updates: object) -> None:
    value = _proof() | updates
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _clear_libpq(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(studio_app.os.environ):
        if name.upper().startswith("PG"):
            monkeypatch.delenv(name, raising=False)


def test_factory_is_inert_without_exact_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AC_LOCAL_STUDIO_VIDEO_ENABLED", raising=False)
    monkeypatch.setattr(
        studio_app,
        "_load_proof",
        lambda: pytest.fail("proof must not load while the factory is disabled"),
    )
    with pytest.raises(RuntimeError, match="exact opt-in"):
        studio_app.create_app()


@pytest.mark.parametrize("value", ["1", "TRUE", "True", "yes", "false", ""])
def test_factory_rejects_ambiguous_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("AC_LOCAL_STUDIO_VIDEO_ENABLED", value)
    with pytest.raises(RuntimeError, match="exact opt-in"):
        studio_app.create_app()


def test_factory_rejects_unsafe_database_before_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_libpq(monkeypatch)
    monkeypatch.setenv("AC_LOCAL_STUDIO_VIDEO_ENABLED", "true")
    monkeypatch.setattr(
        studio_app.application_module,
        "settings",
        _settings(database_url="postgresql+psycopg://ac_runtime:unused@db.invalid/ac_platform"),
    )
    monkeypatch.setattr(
        studio_app,
        "_load_proof",
        lambda: pytest.fail("unsafe target must fail before scanner evidence is read"),
    )
    with pytest.raises(ValueError, match="isolated loopback"):
        studio_app.create_app()


def test_strict_proof_file_and_current_policy(tmp_path: Path) -> None:
    path = tmp_path / "readiness.json"
    _write_proof(path)
    proof = studio_app._load_proof(path)
    assert proof.host == "127.0.0.1" and proof.port == 13310
    assert proof.max_source_bytes == 2_000_000_000
    assert proof.max_scan_size >= 2 * proof.max_source_bytes

    _write_proof(path, unexpected=True)
    with pytest.raises(RuntimeError, match="proof is unavailable"):
        studio_app._load_proof(path)

    past = datetime.now(UTC) - timedelta(hours=2)
    _write_proof(
        path,
        verified_at=past.isoformat(),
        expires_at=(past + timedelta(hours=1)).isoformat(),
    )
    with pytest.raises(RuntimeError, match="proof is unavailable"):
        studio_app._load_proof(path)


def test_proof_loader_rejects_linked_file(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    linked = tmp_path / "linked.json"
    _write_proof(real)
    try:
        linked.symlink_to(real)
    except OSError:
        pytest.skip("symlink creation is unavailable for this Windows account")
    with pytest.raises(RuntimeError, match="proof is unavailable"):
        studio_app._load_proof(linked)


def test_live_verification_requires_ping_version_clean_and_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = _proof_model()
    commands: list[bytes] = []

    def command(_config: object, value: bytes) -> bytes:
        commands.append(value)
        return b"PONG\x00" if value == b"zPING\x00" else b"ClamAV 1.4.2/1/test\x00"

    class Scanner:
        def __init__(self, _config: object) -> None:
            pass

        def scan(self, **kwargs: object) -> ScanResult:
            key = kwargs["object_key"]
            return (
                ScanResult(True, verified_checksum_sha256=str(kwargs["checksum_sha256"]))
                if key == "scanner-readiness/clean.mp4"
                else ScanResult(False, "MALWARE_DETECTED")
            )

    monkeypatch.setattr(studio_app, "_clamd_command", command)
    monkeypatch.setattr(studio_app, "ClamAVContentScanner", Scanner)
    config = studio_app.ClamAVScannerConfig(
        host="127.0.0.1", port=13310, max_content_bytes=2_000_000_000
    )
    studio_app._verify_scanner(config, proof)
    assert commands == [b"zPING\x00", b"zVERSION\x00"]

    proof = proof.model_copy(update={"clamd_version": "1.4.3"})
    with pytest.raises(RuntimeError, match="live verification failed"):
        studio_app._verify_scanner(config, proof)


def test_factory_composes_exact_real_graph_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_libpq(monkeypatch)
    proof_path = tmp_path / "proof.json"
    video_root = tmp_path / "video-objects"
    _write_proof(proof_path)
    settings = _settings()
    monkeypatch.setenv("AC_LOCAL_STUDIO_VIDEO_ENABLED", "true")
    monkeypatch.setattr(studio_app, "_PROOF_PATH", proof_path)
    monkeypatch.setattr(studio_app, "_VIDEO_ROOT", video_root)
    monkeypatch.setattr(studio_app.application_module, "settings", settings)

    application = studio_app.create_app()
    runtime = application.state.studio_video_worker
    readiness = application.state.local_studio_video_readiness
    assert runtime is not None
    assert readiness.available() is False
    paths = application.openapi()["paths"]
    assert "/v1/media/{kind}/{object_key}" in paths
    assert "/v1/admin/studio/programs/{program_id}/video-uploads" in paths
    studio = runtime.pipeline.service
    assert studio.storage.root == video_root
    assert type(studio.scanner) is studio_app.ClamAVContentScanner
    assert studio.storage.max_object_bytes == 2_000_000_000


@pytest.mark.asyncio
async def test_stale_readiness_prevents_worker_claim_until_refreshed() -> None:
    class Worker:
        def __init__(self) -> None:
            self.calls = 0

        async def run_once(self) -> studio_app.StudioVideoWorkerResult:
            self.calls += 1
            return studio_app.StudioVideoWorkerResult(claimed=1, succeeded=1)

    readiness = studio_app._Readiness(_proof_model())
    worker = Worker()
    gated = studio_app._ReadyWorker(readiness, worker)
    assert await gated.run_once() == studio_app.StudioVideoWorkerResult()
    assert worker.calls == 0
    readiness.scanner_ready = True
    assert (await gated.run_once()).succeeded == 1
    assert worker.calls == 1


@pytest.mark.asyncio
async def test_monitor_reloads_new_managed_proof_before_restoring_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _proof_model()
    replacement = initial.model_copy(update={"evidence_sha256": "9" * 64, "clamd_version": "1.5.4"})
    readiness = studio_app._Readiness(initial)
    readiness.scanner_ready = True
    stop = asyncio.Event()
    checked: list[studio_app.LocalStudioVideoScannerReadiness] = []

    monkeypatch.setattr(studio_app, "_MONITOR_INTERVAL", timedelta(0))
    monkeypatch.setattr(studio_app, "_load_proof", lambda: replacement)

    async def check(
        _executor: object,
        _config: object,
        proof: studio_app.LocalStudioVideoScannerReadiness,
    ) -> None:
        assert not readiness.scanner_ready
        checked.append(proof)
        stop.set()

    monkeypatch.setattr(studio_app, "_run_check", check)
    await studio_app._monitor_scanner(
        stop,
        readiness,
        object(),  # type: ignore[arg-type]
        studio_app.ClamAVScannerConfig(host="127.0.0.1", port=13310),
    )
    assert checked == [replacement]
    assert readiness.proof is replacement
    assert readiness.scanner_ready


@pytest.mark.asyncio
async def test_expired_readiness_blocks_upload_and_health_but_not_playback() -> None:
    proof = _proof_model()
    proof = proof.model_copy(
        update={
            "verified_at": datetime.now(UTC) - timedelta(hours=2),
            "expires_at": datetime.now(UTC) - timedelta(hours=1),
        }
    )
    readiness = studio_app._Readiness(proof)
    readiness.scanner_ready = True
    app = FastAPI()

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/v1/media/playback/{key}")
    async def playback(key: str) -> dict[str, str]:
        return {"key": key}

    @app.post("/v1/admin/studio/programs/{program_id}/video-uploads")
    async def upload(program_id: str) -> dict[str, str]:
        return {"program_id": program_id}

    @app.get("/v1/admin/studio/programs/{program_id}/video-upload-capability")
    async def capability(program_id: str, request: studio_app.Request) -> studio_app.Response:
        if request.headers.get("x-deny") == "true":
            return studio_app.JSONResponse({"detail": "denied"}, status_code=403)
        return studio_app.JSONResponse({"program_id": program_id, "available": True})

    studio_app._install_readiness_gate(app, readiness)
    program_id = "00000000-0000-0000-0000-000000000000"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://learner.localhost"
    ) as client:
        assert (await client.get("/v1/media/playback/already-ready")).status_code == 200
        health = await client.get("/health/ready")
        assert health.status_code == 503 and health.json()["code"] == "not_ready"
        blocked = await client.post(f"/v1/admin/studio/programs/{program_id}/video-uploads")
        assert blocked.status_code == 503
        capability_response = await client.get(
            f"/v1/admin/studio/programs/{program_id}/video-upload-capability"
        )
        assert capability_response.status_code == 200
        assert capability_response.json()["available"] is False
        denied = await client.get(
            f"/v1/admin/studio/programs/{program_id}/video-upload-capability",
            headers={"x-deny": "true"},
        )
        assert denied.status_code == 403


class _BlockingRunner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.started = asyncio.Event()
        self.stopping = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, stop: asyncio.Event) -> StudioVideoRunnerSummary:
        self.events.append("runner_started")
        self.started.set()
        await stop.wait()
        self.events.append("runner_stopping")
        self.stopping.set()
        await self.release.wait()
        self.events.append("runner_stopped")
        return StudioVideoRunnerSummary()


@pytest.mark.asyncio
async def test_lifecycle_drains_runner_before_original_database_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    app = FastAPI()

    @asynccontextmanager
    async def original(_app: FastAPI):  # type: ignore[no-untyped-def]
        events.append("database_started")
        yield
        events.append("database_disposed")

    app.router.lifespan_context = original
    proof = _proof_model()
    readiness, runner = studio_app._Readiness(proof), _BlockingRunner(events)

    async def verified(*_args: object) -> None:
        events.append("scanner_verified")

    monkeypatch.setattr(studio_app, "_run_check", verified)
    studio_app._install_lifecycle(
        app,
        readiness,
        runner,  # type: ignore[arg-type]
        studio_app.ClamAVScannerConfig(host="127.0.0.1", port=13310),
    )
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    await runner.started.wait()
    assert readiness.available()
    closing = asyncio.create_task(context.__aexit__(None, None, None))
    await runner.stopping.wait()
    assert not closing.done() and "database_disposed" not in events
    runner.release.set()
    await closing
    assert events[-2:] == ["runner_stopped", "database_disposed"]
    assert readiness.scanner_ready is False


@pytest.mark.asyncio
async def test_unexpected_runner_failure_marks_readiness_and_surfaces_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()

    @asynccontextmanager
    async def original(_app: FastAPI):  # type: ignore[no-untyped-def]
        yield

    class FailedRunner:
        def __init__(self) -> None:
            self.failed = asyncio.Event()

        async def run(self, _stop: asyncio.Event) -> StudioVideoRunnerSummary:
            self.failed.set()
            raise RuntimeError("synthetic runner failure")

    app.router.lifespan_context = original
    proof = _proof_model()
    readiness = studio_app._Readiness(proof)

    async def verified(*_args: object) -> None:
        pass

    monkeypatch.setattr(studio_app, "_run_check", verified)
    failed_runner = FailedRunner()
    studio_app._install_lifecycle(
        app,
        readiness,
        failed_runner,  # type: ignore[arg-type]
        studio_app.ClamAVScannerConfig(host="127.0.0.1", port=13310),
    )
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    await failed_runner.failed.wait()
    await asyncio.sleep(0)
    assert readiness.available() is False
    with pytest.raises(RuntimeError, match="synthetic runner failure"):
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_repeated_native_cancellation_drains_all_owned_tasks() -> None:
    first_release, second_release = asyncio.Event(), asyncio.Event()

    async def blocked(release: asyncio.Event) -> object:
        await release.wait()
        return object()

    first = asyncio.create_task(blocked(first_release))
    second = asyncio.create_task(blocked(second_release))
    draining = asyncio.create_task(studio_app._drain_all((first, second)))
    await asyncio.sleep(0)
    draining.cancel()
    draining.cancel()
    await asyncio.sleep(0)
    assert not draining.done() and not first.cancelled() and not second.cancelled()
    first_release.set()
    await asyncio.sleep(0)
    assert not draining.done()
    draining.cancel()
    second_release.set()
    with pytest.raises(asyncio.CancelledError):
        await draining
    assert first.done() and second.done()
