"""Dev logo scanner isolation/proof regressions; never access Docker or the host."""

import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "infra/application/development/organisation-avatar"
spec = importlib.util.spec_from_file_location("dev_logo_proof", PROFILE / "prove.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


@pytest.fixture
def scanner(tmp_path, monkeypatch):
    monkeypatch.setattr(proof, "DIRECTORY", tmp_path)
    for name in proof.FILES:
        (tmp_path / name).write_bytes((PROFILE / name).read_bytes())
    value = {
        "Config": {
            "Image": proof.IMAGE,
            "User": "100:100",
            "Entrypoint": ["/bin/sh", proof.FILES["entrypoint.sh"]],
        },
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "HostConfig": {
            "Privileged": False,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 1536 * 1024 * 1024,
            "MemorySwap": 1536 * 1024 * 1024,
            "NanoCpus": 500_000_000,
            "PidsLimit": 32,
            "NetworkMode": "ac-dev-organisation-avatar_default",
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16777216,uid=100,gid=100,mode=0700"},  # noqa: S108
        },
        "Mounts": [
            *[
                {"Type": "bind", "Destination": dest, "Source": str(tmp_path / name), "RW": False}
                for name, dest in proof.FILES.items()
            ],
            {
                "Type": "bind",
                "Destination": "/var/lib/clamav",
                "Source": str(proof.DATABASE),
                "RW": True,
            },
            {
                "Type": "bind",
                "Destination": str(proof.SOCKET_ROOT),
                "Source": str(proof.SOCKET_ROOT),
                "RW": True,
            },
        ],
    }
    real_stat = Path.stat

    def owned(path, **kwargs):
        result = real_stat(path, **kwargs)
        if path.parent == tmp_path:
            from types import SimpleNamespace

            return SimpleNamespace(st_uid=0, st_mode=result.st_mode)
        return result

    monkeypatch.setattr(Path, "stat", owned)
    monkeypatch.setattr(
        proof,
        "run",
        lambda *args: sha256((tmp_path / Path(args[-1]).name).read_bytes()).hexdigest() + "  file",
    )
    return value


def test_admits_reviewed_container_and_rejects_changed_config_hash(scanner, monkeypatch):
    proof.verify_container(scanner)
    monkeypatch.setattr(proof, "run", lambda *args: "0" * 64 + "  file")
    with pytest.raises(ValueError, match="scanner_source_mismatch"):
        proof.verify_container(scanner)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Privileged", True),
        ("CapAdd", ["SYS_ADMIN"]),
        ("PortBindings", {"3310/tcp": [{"HostPort": "3310"}]}),
        ("ReadonlyRootfs", False),
        ("Memory", 2 * 1024**3),
        ("MemorySwap", -1),
        ("NanoCpus", 2_000_000_000),
        ("PidsLimit", -1),
        ("NetworkMode", "host"),
    ],
)
def test_refuses_host_exposure_and_unbounded_resources(scanner, field, value):
    unsafe = deepcopy(scanner)
    unsafe["HostConfig"][field] = value
    with pytest.raises(ValueError, match="scanner_isolation_invalid"):
        proof.verify_container(unsafe)


def test_refuses_foreign_environment_mount(scanner):
    scanner["Mounts"][-1]["Source"] = "/srv/authority-closers/sales-xray/production"
    with pytest.raises(ValueError, match="scanner_mounts_invalid"):
        proof.verify_container(scanner)


@pytest.mark.parametrize("age_hours", [0, 49, -2])
def test_proof_checks_loaded_signature_identity_and_freshness(tmp_path, monkeypatch, age_hours):
    monkeypatch.setattr(proof, "DATABASE", tmp_path)
    (tmp_path / "daily.cvd").touch()
    monkeypatch.setattr(proof, "verify_container", lambda value: None)
    built = datetime.now(UTC) - timedelta(hours=age_hours, minutes=1)

    def run(*args):
        if args[0] == "inspect":
            return "[{}]"
        return "Version: 42\nBuild time: " + built.strftime("%d %b %Y %H:%M %z")

    monkeypatch.setattr(proof, "run", run)
    monkeypatch.setattr(
        proof,
        "command",
        lambda body: b"PONG\0" if body == b"zPING\0" else b"ClamAV 1.5.4/42/today\0",
    )
    monkeypatch.setattr(
        proof,
        "scan",
        lambda body: (
            b"stream: Eicar-Test-Signature FOUND\0" if b"EICAR" in body else b"stream: OK\0"
        ),
    )
    if age_hours == 0:
        assert proof.prove()["result"] == "PASS"
    else:
        with pytest.raises(ValueError, match="signatures_stale"):
            proof.prove()


def test_profile_cannot_expose_tcp_or_foreign_storage_and_survives_restart():
    compose = (PROFILE / "compose.yaml").read_text()
    assert "ports:" not in compose and "network_mode:" not in compose
    assert "create_host_path: false" in compose
    assert not any(value in compose for value in ("staging", "production", "avatar-objects"))
    policy = (PROFILE / "clamd.conf").read_text()
    assert "TCPSocket" not in policy and "AlertExceedsMax yes" in policy
    assert "StreamMaxLength 2097152" in policy and "MaxScanSize 8388608" in policy
    assert "ConcurrentDatabaseReload no" in policy
    entrypoint = (PROFILE / "entrypoint.sh").read_text()
    assert "rm -f /run/ac-dev-organisation-avatar/clamd.sock /tmp/clamd.sock" in entrypoint
    assert "exec /init-unprivileged" in entrypoint
    unit = (PROFILE / "ac-dev-organisation-avatar.service").read_text()
    assert "ExecStartPost=" in unit and "prove.py" in unit
    assert "After=docker.service network-online.target systemd-tmpfiles-setup.service" in unit
    overlay = (PROFILE / "api.conf").read_text()
    assert "Requires=ac-dev-organisation-avatar.service" in overlay
    assert "BindReadOnlyPaths=/run/ac-dev-organisation-avatar" in overlay
    assert "AC_MEDIA_FILESYSTEM_ENABLED" not in overlay
