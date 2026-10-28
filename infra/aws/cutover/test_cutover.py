# ruff: noqa: S603, S607 -- reviewed argv, fixed utilities, no shell interpolation
"""Cutover safety/failure recovery and real encryption/rsync tests; no production I/O."""

import json
import os
import runpy
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
DRIVER = runpy.run_path(str(ROOT / "cutover.py"))
BACKUP = runpy.run_path(str(ROOT / "backup.py"))


@pytest.fixture
def kit(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"environment": "fictional", "hooks": {}, "files": []}))
    return DRIVER["Kit"](config, tmp_path / "evidence")


def test_default_production_invocation_executes_nothing(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.json"
    config.write_text('{"environment":"production"}')
    monkeypatch.setattr(
        sys,
        "argv",
        ["cutover", "freeze-and-move", "--config", str(config), "--evidence", str(tmp_path / "e")],
    )
    DRIVER["main"]()
    assert json.loads(capsys.readouterr().out)["execution"] is False
    assert not (tmp_path / "e/state.json").exists()


def test_execution_requires_config_bound_owner_record(tmp_path, monkeypatch):
    config, approval = tmp_path / "config.json", tmp_path / "approval.json"
    config.write_text('{"environment":"production"}')
    approval.write_text(
        '{"config_sha256":"wrong","action":"presync","owner_record":"fictional example"}'
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cutover",
            "presync",
            "--execute",
            "--config",
            str(config),
            "--evidence",
            str(tmp_path / "e"),
            "--approval-record",
            str(approval),
        ],
    )
    with pytest.raises(RuntimeError, match="approval"):
        DRIVER["main"]()


def test_config_drift_cannot_reuse_evidence(kit, tmp_path):
    kit.save()
    config = tmp_path / "config.json"
    config.write_text('{"environment":"changed"}')
    with pytest.raises(RuntimeError, match="differs"):
        DRIVER["Kit"](config, kit.root)


def test_freeze_drain_and_verification_precede_start(kit, monkeypatch):
    seen = []
    monkeypatch.setattr(kit, "hook", lambda name: seen.append(name))
    monkeypatch.setattr(
        kit, "db", lambda side, action, data=None: seen.append(action) or b"PGDMP-fixture"
    )
    monkeypatch.setattr(kit, "sync", lambda reverse=False: seen.append("delta"))
    monkeypatch.setattr(kit, "verify", lambda reverse=False: seen.append("verify"))
    kit.state["phase"] = "presynced"
    kit.move()
    assert seen == DRIVER["FORWARD"]
    assert kit.state["phase"] == "target-held"


def test_restore_failure_never_starts_target(kit, monkeypatch):
    seen = []
    monkeypatch.setattr(kit, "hook", lambda name: seen.append(name))

    def db(side, action, data=None):
        if action == "restore":
            raise RuntimeError("fictional failure")
        return b"PGDMP-fixture"

    monkeypatch.setattr(kit, "db", db)
    kit.state["phase"] = "presynced"
    with pytest.raises(RuntimeError):
        kit.move()
    assert "start_target_held" not in seen
    assert (
        json.loads((kit.root / "timings.jsonl").read_text().splitlines()[-1])["status"] == "failed"
    )


def test_reverse_move_saves_old_source_before_overwrite(kit, monkeypatch):
    seen = []
    monkeypatch.setattr(kit, "hook", lambda name: seen.append(name))
    monkeypatch.setattr(
        kit, "db", lambda side, action, data=None: seen.append((side, action)) or b"PGDMP-fixture"
    )
    monkeypatch.setattr(kit, "sync", lambda reverse=False: seen.append(("delta", reverse)))
    monkeypatch.setattr(kit, "verify", lambda reverse=False: seen.append(("verify", reverse)))
    kit.state["phase"] = "target-live"
    kit.move(True)
    assert seen.index(("source", "dump")) < seen.index(("source", "restore"))
    assert seen.index("fence_target") < seen.index(("target", "dump"))
    assert (kit.root / "safety_dump.dump").read_bytes().startswith(b"PGDMP")
    assert kit.state["phase"] == "source-held"


def test_row_count_mismatch_blocks_open(kit, monkeypatch):
    monkeypatch.setattr(
        kit,
        "db",
        lambda side, action: json.dumps({"tables": [1 if side == "source" else 2]}).encode(),
    )
    with pytest.raises(RuntimeError, match="inventory mismatch"):
        kit.verify()


def test_manifest_rejects_links_and_detects_content_change(tmp_path):
    manifest = runpy.run_path(str(ROOT / "endpoint.py"))["manifest"]
    (tmp_path / "object").write_text("fictional bytes")
    before = manifest(tmp_path)
    (tmp_path / "object").write_text("different bytes")
    assert manifest(tmp_path) != before
    (tmp_path / "link").symlink_to(tmp_path / "object")
    with pytest.raises(RuntimeError, match="links"):
        manifest(tmp_path)


def test_rsync_resumes_and_preserves_unapproved_extra_files(kit, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "recording").write_bytes(b"x" * 100000)
    (target / "recording").write_bytes(b"x" * 1000)
    (target / "keep").write_text("not approved for deletion")
    kit.c.update(source={}, target={}, files=[{"source": str(source), "target": str(target)}])
    kit.sync()
    assert (source / "recording").read_bytes() == (target / "recording").read_bytes()
    assert (target / "keep").exists()


def test_backup_retention_and_encrypted_roundtrip(tmp_path, monkeypatch):
    root, sink = tmp_path / "backups", tmp_path / "sink"
    root.mkdir()
    old = root / "20000101T000000.000000Z"
    old.mkdir()
    for name in ["database.dump", "receipt.json"]:
        (old / name).write_text("old fictional backup")
    os.utime(old, (time.time() - 90000,) * 2)
    key, cert = tmp_path / "fixture-key.pem", tmp_path / "fixture-cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=fictional-cutover/",
            "-days",
            "1",
        ],
        capture_output=True,
        check=True,
    )
    capture = BACKUP["capture"]
    monkeypatch.setitem(capture.__globals__, "run", lambda *a, **kw: b"PGDMP-fictional backup")
    capture({"database": ["fictional"]}, root)
    assert not old.exists()
    monkeypatch.setitem(capture.__globals__, "run", BACKUP["run"])
    BACKUP["archive"]({"encryption_certificate": str(cert)}, root, sink)
    encrypted = next(sink.iterdir())
    assert b"PGDMP" not in encrypted.read_bytes()
    result = subprocess.run(
        [
            "openssl",
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-in",
            str(encrypted),
            "-recip",
            str(cert),
            "-inkey",
            str(key),
        ],
        capture_output=True,
        check=True,
    )
    assert b"PGDMP-fictional backup" in result.stdout


def test_archive_refuses_stale_dump(tmp_path):
    old = tmp_path / "20000101T000000.000000Z"
    old.mkdir()
    os.utime(old, (time.time() - 1300,) * 2)
    with pytest.raises(RuntimeError, match="fresh"):
        BACKUP["archive"]({}, tmp_path, tmp_path / "sink")


def test_tunnel_is_loopback_only():
    import argparse

    namespace = runpy.run_path(str(ROOT / "ops-repoint"))
    cmd = namespace["argv"](
        argparse.Namespace(
            mode="tunnel",
            identity="/fixture/key",
            host="fixture",
            local_port=15439,
            remote_port=15432,
        )
    )
    assert "127.0.0.1:15439:127.0.0.1:15432" in cmd
    assert "ExitOnForwardFailure=yes" in cmd


def test_restore_refuses_real_db_before_docker(monkeypatch):
    namespace = runpy.run_path(str(ROOT / "endpoint.py"))
    monkeypatch.setattr(
        sys, "argv", ["endpoint", "database", "container", "ac_platform", "restore"]
    )
    with pytest.raises(RuntimeError, match="production permit"):
        namespace["main"]()


def test_freeze_deadline_never_starts_target(kit, monkeypatch):
    seen = []
    kit.c["freeze_budget_seconds"] = -1
    kit.state["phase"] = "presynced"
    monkeypatch.setattr(kit, "hook", lambda name: seen.append(name))
    with pytest.raises(RuntimeError, match="budget exceeded"):
        kit.move()
    assert seen == ["hold_source"]
    assert kit.state["phase"] == "moving-forward"


def test_unclean_worker_exit_refuses_drain(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(ROOT / "host.py"))
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "inventory_review_record": "fixture",
                "writers": ["fixture-worker"],
                "drain": ["fixture-worker"],
                "held_services": [],
                "restart_policies": {"fixture-worker": "unless-stopped"},
                "writer_units": ["fixture.timer"],
            }
        )
    )
    seen = []
    running = iter(["true", "false"])

    def run(argv):
        seen.append(argv)
        if "{{.HostConfig.RestartPolicy.Name}}" in argv:
            return "unless-stopped"
        if "{{.State.Running}}" in argv:
            return next(running)
        if "{{.State.ExitCode}}" in argv:
            return "137"
        return ""

    monkeypatch.setitem(namespace["main"].__globals__, "run", run)
    monkeypatch.setattr(sys, "argv", ["host", "--profile", str(profile), "--execute", "drain"])
    with pytest.raises(RuntimeError, match="cleanly"):
        namespace["main"]()
    assert ["docker", "kill", "--signal=TERM", "fixture-worker"] in seen
    assert ["systemctl", "stop", "fixture.timer"] in seen
    assert seen.index(["docker", "update", "--restart=no", "fixture-worker"]) < seen.index(
        ["docker", "kill", "--signal=TERM", "fixture-worker"]
    )


def test_failed_canary_and_failed_hold_still_records_write_exposure(kit, monkeypatch):
    kit.state["phase"] = "target-held"
    seen = []

    def hook(name):
        seen.append(name)
        if name in {"target_canary", "hold_target"}:
            raise RuntimeError("fixture failed")

    monkeypatch.setattr(kit, "hook", hook)
    main = DRIVER["main"]
    monkeypatch.setitem(main.__globals__, "Kit", lambda *args: kit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cutover",
            "switch",
            "--config",
            "fixture",
            "--evidence",
            str(kit.root),
            "--execute",
            "--routes-confirmed",
        ],
    )
    with pytest.raises(RuntimeError):
        main()
    assert kit.state["phase"] == "switch-failed"
    assert seen[-2:] == ["drain_target", "fence_target"]
    assert json.loads(kit.state_path.read_text())["phase"] == "switch-failed"


def test_remote_cli_arguments_are_quoted():
    import argparse
    import shlex

    namespace = runpy.run_path(str(ROOT / "ops-repoint"))
    payload = "literal $(do-not-run); --example"
    cmd = namespace["argv"](
        argparse.Namespace(
            mode="bugs", identity="/fixture/key", host="fixture", arguments=["show", payload]
        )
    )
    assert shlex.split(cmd[-1])[-1] == payload


def test_decrypted_archive_is_verified_before_writing(tmp_path):
    recover = runpy.run_path(str(ROOT / "recover-archive.py"))["recover"]
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=fixture/",
            "-days",
            "1",
        ],
        capture_output=True,
        check=True,
    )
    plain, encrypted = tmp_path / "invalid", tmp_path / "invalid.cms"
    plain.write_bytes(b"not a backup archive")
    subprocess.run(
        [
            "openssl",
            "cms",
            "-encrypt",
            "-binary",
            "-aes-256-cbc",
            "-outform",
            "DER",
            "-in",
            str(plain),
            "-out",
            str(encrypted),
            str(cert),
        ],
        capture_output=True,
        check=True,
    )
    with pytest.raises(tarfile.ReadError):
        recover(encrypted, cert, key, tmp_path / "out")
    assert not (tmp_path / "out").exists()
