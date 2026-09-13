from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import native_runtime, signals
from scripts import native_runtime_helper

IMAGE = "sha256:" + "a" * 64


@pytest.mark.parametrize("probe_status,remaining", [(0, b"container-id\n"), (1, b"")])
def test_cleanup_requires_confirmed_container_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe_status: int, remaining: bytes
) -> None:
    commands: list[list[str]] = []

    def command(argv: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(argv)
        return SimpleNamespace(returncode=probe_status, stdout=remaining)

    monkeypatch.setattr(native_runtime.subprocess, "run", command)
    runtime = native_runtime.DockerNativeRuntime(IMAGE, workspace_root=tmp_path)
    with pytest.raises(native_runtime.NativeRuntimeError, match="cleanup_failed"):
        runtime._remove_container("ac-native-synthetic")
    assert commands[0][1:3] == ["rm", "--force"]
    assert commands[1][1:3] == ["container", "ls"]


def test_cleanup_accepts_already_auto_removed_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter(
        [
            SimpleNamespace(returncode=1, stdout=b""),
            SimpleNamespace(returncode=0, stdout=b""),
        ]
    )
    monkeypatch.setattr(native_runtime.subprocess, "run", lambda *args, **kwargs: next(responses))
    native_runtime.DockerNativeRuntime(IMAGE, workspace_root=tmp_path)._remove_container(
        "ac-native-synthetic"
    )


def _checkpoint_fixture(source: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    sample_count = 640
    raw = destination.parent / "fixture.raw"
    metadata = signals._feature_metadata(16000, 1, sample_count)
    rows = metadata["rows"]
    with raw.open("wb") as stream:
        for index in range(rows):
            start = float(index * metadata["hop_samples"])
            valid = float(min(metadata["window_samples"], sample_count - int(start)))
            stream.write(
                signals._RAW_ROW.pack(
                    start,
                    0.0,
                    valid,
                    0.1,
                    -20.0,
                    0.5,
                    0.0,
                    0.0,
                    100.0,
                    40.0,
                    150.0,
                    0.5,
                    1.0,
                    0.1,
                    200.0,
                    0.8,
                    0.0,
                    0.0,
                )
            )
    features = destination / "features.aaf"
    signals.pack_features(raw, features, 16000, 1, sample_count)
    feature_sha = hashlib.sha256(features.read_bytes()).hexdigest()
    acoustics = dict(metadata)
    acoustics.update(
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        feature_sha256=feature_sha,
    )
    source_sha = acoustics["source_sha256"]
    payload = {
        "acoustics": acoustics,
        "media_duration_ms": 40,
        "native_receipt": {
            "binary_sha256": "b" * 64,
            "mode": "fft",
            "rows": rows,
            "source_sha256": source_sha,
        },
        "schema": "ac.sales-xray.signal-checkpoint/1",
        "source_bytes": source.stat().st_size,
        "source_sha256": source_sha,
        "stage": "C1",
        "timebase": {"clock": "decoded_audio_track", "rate": 16000},
        "feature_sha256": feature_sha,
    }
    (destination / "checkpoint.json").write_bytes(native_runtime._canonical_json(payload) + b"\n")


def _output_mount(command: tuple[str, ...]) -> Path:
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    mount = next(value for value in mounts if "target=/output" in value)
    return Path(mount.split("source=", 1)[1].split(",target=", 1)[0])


def test_docker_adapter_uses_fixed_isolated_command_and_promotes_verified_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"synthetic hosted source")
    calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], name: str, timeout: float) -> None:
        calls.append(command)
        assert name.endswith(uuid.hex)
        assert timeout == 5.0
        staging = _output_mount(command)
        _checkpoint_fixture(source, staging / "checkpoint")

    uuid = uuid4()
    runtime = native_runtime.DockerNativeRuntime(
        IMAGE,
        workspace_root=tmp_path,
        timeout_seconds=5,
        runner=runner,
    )
    result = runtime.inspect(
        source,
        tmp_path / "result",
        job_id=uuid,
        rate=16000,
    )

    assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["acoustics"]["rate"] == 16000
    assert (tmp_path / "result" / "features.aaf").is_file()
    assert not list(tmp_path.glob(".native-output-*"))
    command = calls[0]
    for flag in (
        "--network=none",
        "--read-only",
        "--user=10001:10001",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=32",
        "--memory=768m",
        "--memory-swap=768m",
        "--cpus=1",
        "--log-driver=none",
        "target=/input/source.media,readonly,bind-propagation=rprivate",
        "target=/output,bind-propagation=rprivate",
    ):
        assert any(flag in entry for entry in command)
    assert "--env-file" not in command
    assert "/var/run/docker.sock" not in command
    program = command[-1]
    assert '"--rate", "16000"' in program
    assert "provider" not in program.lower()


def test_docker_adapter_stages_on_helper_quota_root_and_publishes_to_worker_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"synthetic quota source")
    quota_root = tmp_path / "native-output-tmpfs"
    quota_root.mkdir(mode=0o700)
    calls: list[tuple[str, ...]] = []

    def fake_statvfs(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(f_frsize=1, f_blocks=64 * 1024 * 1024)

    monkeypatch.setattr(native_runtime.os, "statvfs", fake_statvfs, raising=False)
    monkeypatch.setattr(native_runtime.stat, "S_IMODE", lambda _mode: 0o700)

    def runner(command: tuple[str, ...], _name: str, _timeout: float) -> None:
        calls.append(command)
        _checkpoint_fixture(source, _output_mount(command) / "checkpoint")

    runtime = native_runtime.DockerNativeRuntime(
        IMAGE,
        workspace_root=tmp_path,
        output_root=quota_root,
        runner=runner,
    )
    result = runtime.inspect(source, tmp_path / "published", job_id=uuid4(), rate=16000)

    mount = _output_mount(calls[0])
    assert mount.parent == quota_root
    assert result["timebase"]["rate"] == 16000
    assert (tmp_path / "published" / "checkpoint.json").is_file()
    assert not list(quota_root.glob(".native-output-*"))


def test_helper_peer_credentials_use_uid_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native_runtime_helper.socket, "SO_PEERCRED", 17, raising=False)

    class FakeChannel:
        def getsockopt(self, *_args: object) -> bytes:
            return struct.pack("3i", 101, 202, 303)

    assert native_runtime_helper._peer_uid(FakeChannel()) == 202  # type: ignore[arg-type]


def test_helper_ignores_disconnected_peer_when_sending_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native_runtime_helper.socket, "SO_PEERCRED", 17, raising=False)

    class DisconnectedChannel:
        timeout: float | None = None

        def getsockopt(self, *_args: object) -> bytes:
            return struct.pack("3i", 101, 202, 303)

        def settimeout(self, value: float) -> None:
            self.timeout = value

        def recv(self, _length: int) -> bytes:
            return b""

        def sendall(self, _data: bytes) -> None:
            raise BrokenPipeError

    native_runtime_helper._handle(  # type: ignore[arg-type]
        DisconnectedChannel(),
        runtime=SimpleNamespace(timeout_seconds=1.0),  # type: ignore[arg-type]
        workspace_root=Path("C:/workspace"),
        image_ref=IMAGE,
        peer_uid=202,
    )


def test_helper_request_frame_has_one_bounded_deadline() -> None:
    request = native_runtime._canonical_json({"schema": native_runtime.NATIVE_RUNTIME_SCHEMA})
    wire = struct.pack(">I", len(request)) + request

    class DripChannel:
        def __init__(self) -> None:
            self.offset = 0
            self.timeouts: list[float] = []

        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)

        def recv(self, length: int) -> bytes:
            block = wire[self.offset : self.offset + length]
            self.offset += len(block)
            return block

    channel = DripChannel()
    parsed = native_runtime_helper._read_request(channel)  # type: ignore[arg-type]
    assert parsed == {"schema": native_runtime.NATIVE_RUNTIME_SCHEMA}
    assert channel.timeouts
    assert all(
        0 < value <= native_runtime_helper._REQUEST_DEADLINE_SECONDS for value in channel.timeouts
    )


@pytest.mark.skipif(not hasattr(os, "chown"), reason="POSIX ownership is unavailable")
def test_native_owner_is_applied_to_staging_and_published_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"synthetic ownership source")
    quota_root = tmp_path / "native-output-tmpfs"
    quota_root.mkdir(mode=0o700)
    owner = (os.getuid(), os.getgid())

    class Usage:
        f_frsize = 1
        f_blocks = 64 * 1024 * 1024

    monkeypatch.setattr(native_runtime.os, "statvfs", lambda _path: Usage(), raising=False)
    monkeypatch.setattr(native_runtime.stat, "S_IMODE", lambda _mode: 0o700)
    calls: list[Path] = []

    def runner(command: tuple[str, ...], _name: str, _timeout: float) -> None:
        mount = _output_mount(command)
        calls.append(mount)
        _checkpoint_fixture(source, mount / "checkpoint")

    runtime = native_runtime.DockerNativeRuntime(
        IMAGE,
        workspace_root=tmp_path,
        output_root=quota_root,
        native_owner=owner,
        runner=runner,
    )
    runtime.inspect(source, tmp_path / "published", job_id=uuid4(), rate=16000)
    assert calls and calls[0].stat().st_uid == owner[0]
    assert (tmp_path / "published").stat().st_uid == owner[0]
    assert (tmp_path / "published" / "features.aaf").stat().st_uid == owner[0]


def test_socket_client_sends_only_bounded_paths_and_validates_output(tmp_path: Path) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"synthetic socket source")
    seen: dict[str, object] = {}

    def exchange(frame: bytes) -> bytes:
        length = struct.unpack(">I", frame[:4])[0]
        request = json.loads(frame[4 : 4 + length])
        seen.update(request)
        _checkpoint_fixture(source, Path(str(request["outdir"])))
        return native_runtime._canonical_json(
            {"schema": native_runtime.NATIVE_RUNTIME_SCHEMA, "ok": True}
        )

    runtime = native_runtime.SocketNativeRuntime(
        Path(tmp_path.anchor) / "ac-native-unit.sock",
        workspace_root=tmp_path,
        expected_image_ref=IMAGE,
        exchange=exchange,
    )
    result = runtime.inspect(
        source,
        tmp_path / "socket-result",
        job_id=uuid4(),
        rate=16000,
    )

    assert result["timebase"]["rate"] == 16000
    assert set(seen) == {
        "schema",
        "operation",
        "source",
        "outdir",
        "job_id",
        "image_ref",
        "rate",
        "source_sha256",
        "source_bytes",
    }
    assert seen["image_ref"] == IMAGE
    assert seen["rate"] == 16000
    assert "audio" not in seen
    assert (tmp_path / "socket-result" / "features.aaf").is_file()


@pytest.mark.parametrize(
    ("image_ref", "expected"),
    [
        ("ac-sales-xray:latest", "native_runtime_configuration_invalid"),
        ("registry.example/ac-sales-xray:1", "native_runtime_configuration_invalid"),
    ],
)
def test_runtime_rejects_mutable_image_refs(tmp_path: Path, image_ref: str, expected: str) -> None:
    with pytest.raises(native_runtime.NativeRuntimeError) as error:
        native_runtime.DockerNativeRuntime(image_ref, workspace_root=tmp_path)
    assert error.value.code == expected


def test_hosted_profile_rejects_48khz_and_output_outside_workspace(tmp_path: Path) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"source")
    runtime = native_runtime.DockerNativeRuntime(
        IMAGE, workspace_root=tmp_path, runner=lambda *_: None
    )
    with pytest.raises(native_runtime.NativeRuntimeError, match="native_runtime_rate_mismatch"):
        runtime.inspect(source, tmp_path / "result", job_id=uuid4(), rate=48000)  # type: ignore[arg-type]
    with pytest.raises(native_runtime.NativeRuntimeError, match="native_runtime_source_invalid"):
        runtime.inspect(
            source,
            tmp_path.parent / "outside-result",
            job_id=uuid4(),
            rate=16000,
        )


def test_checkpoint_source_or_feature_damage_is_rejected_and_staging_is_clean(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"source")
    output = tmp_path / "result"

    def runner(command: tuple[str, ...], name: str, timeout: float) -> None:
        staging = _output_mount(command)
        _checkpoint_fixture(source, staging / "checkpoint")
        checkpoint = staging / "checkpoint" / "checkpoint.json"
        payload = json.loads(checkpoint.read_text())
        payload["source_bytes"] += 1
        checkpoint.write_bytes(native_runtime._canonical_json(payload) + b"\n")

    runtime = native_runtime.DockerNativeRuntime(IMAGE, workspace_root=tmp_path, runner=runner)
    with pytest.raises(
        native_runtime.NativeRuntimeError,
        match="native_runtime_source_binding_mismatch",
    ):
        runtime.inspect(source, output, job_id=uuid4(), rate=16000)
    assert not output.exists()
    assert not list(tmp_path.glob(".native-output-*"))
