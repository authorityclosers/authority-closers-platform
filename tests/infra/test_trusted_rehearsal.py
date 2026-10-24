"""Fictional AUT-2216 controls; no Docker, root, credentials or staging access."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "trusted_rehearsal", ROOT / "infra/release/trusted_rehearsal/harness.py"
)
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)
KEY = b"fictional-test-key-only-32-bytes!!"
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
CANDIDATE, BASE = "a" * 40, "b" * 40
CONFIG = {"bundle_sha256": "c" * 64, "runner_image": "ac/fixture@sha256:" + "d" * 64}


def record(**changes):
    return {
        "schema": "ac.schema_rehearsal/2",
        "candidate": CANDIDATE,
        "base": BASE,
        **CONFIG,
        "result": "PASS",
        "exported_at": (NOW - timedelta(minutes=5)).isoformat(),
        "finished_at": (NOW - timedelta(minutes=1)).isoformat(),
        "manifest_sha256": "e" * 64,
        "dump_sha256": "f" * 64,
        "alembic_revision": "20261023_0127",
        "release_id": "1" * 40,
        **changes,
    }


def test_passing_receipt_is_exact_and_authenticated():
    value = record()
    assert h.validate_receipt(h.seal(value, KEY), KEY, CONFIG, CANDIDATE, BASE, NOW) == value


@pytest.mark.parametrize(
    "changes",
    [
        {"candidate": "2" * 40},
        {"base": "3" * 40},
        {"result": "FAIL"},
        {"bundle_sha256": "4" * 64},
        {"runner_image": "untrusted:latest"},
        {"finished_at": (NOW - timedelta(hours=2)).isoformat()},
        {"exported_at": (NOW - timedelta(hours=25)).isoformat()},
        {"exported_at": (NOW + timedelta(minutes=1)).isoformat()},
        {"finished_at": (NOW + timedelta(minutes=1)).isoformat()},
        {"finished_at": "2026-10-24T11:59:00"},
        {"manifest_sha256": "missing"},
        {"dump_sha256": "missing"},
        {"schema": "ac.schema_rehearsal/1"},
        {"extra": True},
        {"release_id": "main"},
        {"alembic_revision": "head"},
    ],
)
def test_signed_but_failed_stale_or_mismatched_receipt_rejected(changes):
    with pytest.raises(h.Refusal):
        h.validate_receipt(h.seal(record(**changes), KEY), KEY, CONFIG, CANDIDATE, BASE, NOW)


def test_candidate_forgery_and_signature_replacement_rejected():
    forged = h.seal(record(), b"candidate-owned-fake-signing-key")
    with pytest.raises(h.Refusal, match="forged"):
        h.validate_receipt(forged, KEY, CONFIG, CANDIDATE, BASE, NOW)
    envelope = h.seal(record(), KEY)
    envelope["record"]["base"] = "0" * 40
    with pytest.raises(h.Refusal, match="forged"):
        h.validate_receipt(envelope, KEY, CONFIG, CANDIDATE, BASE, NOW)


def test_missing_receipt_and_untrusted_location_cannot_be_selected(monkeypatch):
    assert h.receipt_path(CANDIDATE, BASE) == h.RECEIPTS / f"{CANDIDATE}-{BASE}.json"
    for candidate in ["../fake", "HEAD", "a" * 39]:
        with pytest.raises(h.Refusal):
            h.receipt_path(candidate, BASE)
    with pytest.raises(h.Refusal):
        h.validate_receipt({}, KEY, CONFIG, CANDIDATE, BASE, NOW)
    for option in [
        "--receipts",
        "--exporter",
        "--validator",
        "--runner-image",
        "--config",
        "--retire-ci",
    ]:
        with pytest.raises(SystemExit):
            h.main(["verify", "--candidate", CANDIDATE, "--base", BASE, option, "/candidate/evil"])


def test_worker_cannot_access_credentials_network_or_host_control(monkeypatch, tmp_path):
    monkeypatch.setenv("AC_DATABASE_URL", "fictional-host-secret")
    monkeypatch.setenv("UNCLASSIFIED_SECRET", "fictional-host-secret")
    monkeypatch.setenv("DOCKER_HOST", "tcp://fictional-evil.invalid")
    source, sockets = tmp_path / "source", tmp_path / "sockets"
    argv = h.worker_argv(
        source, sockets, CONFIG["runner_image"], "fixture-worker", "upgrade", "0128"
    )
    for flag in [
        "--pull=never",
        "--network=none",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--ipc=none",
        "--pids-limit=128",
        "--memory=768m",
        "--memory-swap=768m",
    ]:
        assert flag in argv
    mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--mount"]
    assert mounts == [
        f"type=bind,src={source},dst=/candidate,readonly",
        f"type=bind,src={sockets},dst=/run/pg,readonly",
    ]
    assert not any(
        x in " ".join(argv)
        for x in ["docker.sock", "fictional-host-secret", "--privileged", "--env-file"]
    )
    assert "--offline" in " ".join(argv) and "--no-python-downloads" in " ".join(argv)
    assert argv[-3:] == ["--", "upgrade", "0128"]
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(h.subprocess, "run", run)
    h.docker(*argv)
    command, kwargs = calls[0]
    assert command[:3] == ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
    assert kwargs["env"] == h.ENV and "DOCKER_HOST" not in kwargs["env"]
    assert "UNCLASSIFIED_SECRET" not in kwargs["env"]


@pytest.mark.parametrize(
    "direction,revision,image",
    [
        ("upgrade", "head;id", CONFIG["runner_image"]),
        ("shell", "0128", CONFIG["runner_image"]),
        ("upgrade", "0128", "ac/fixture:latest"),
    ],
)
def test_worker_arguments_cannot_inject_commands(direction, revision, image, tmp_path):
    with pytest.raises(h.Refusal):
        h.worker_argv(tmp_path, tmp_path, image, "fixture", direction, revision)


def test_install_pin_rejects_candidate_exporter_validator_and_shadowing(tmp_path, monkeypatch):
    bundle = tmp_path / "installed"
    pins = {}
    for name in h.TRUSTED:
        p = bundle / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# reviewed fictional trusted tool\n")
        pins[name] = h.digest(p)
    (bundle / "pins.json").write_bytes(h.canonical(pins))
    config_path = tmp_path / "config.json"
    config = CONFIG | {
        "bundle": str(bundle),
        "bundle_sha256": hashlib.sha256(h.canonical(pins)).hexdigest(),
    }
    config_path.write_bytes(h.canonical(config))
    monkeypatch.setattr(h, "CONFIG", config_path)
    monkeypatch.setattr(h, "__file__", str(bundle / "infra/release/trusted_rehearsal/harness.py"))
    # Fixture tests byte-pinning separately from the production root-owner check.
    monkeypatch.setattr(h, "protected", lambda *a, **k: None)
    assert h.installation() == config
    for name in ["scripts/ops/export_migration_schema.py", "scripts/ci/migration_schema_gate.py"]:
        path = bundle / name
        original = path.read_bytes()
        path.write_text('raise RuntimeError("fictional candidate replacement")')
        with pytest.raises(h.Refusal, match="changed"):
            h.installation()
        path.write_bytes(original)
    (bundle / "scripts/__init__.py").write_text('raise RuntimeError("shadowed")')
    with pytest.raises(h.Refusal, match="unlisted"):
        h.installation()


def test_nonroot_cannot_authorize_or_rehearse(monkeypatch, capsys):
    monkeypatch.setattr(h.os, "geteuid", lambda: 12345)
    monkeypatch.setattr(h, "installation", lambda: pytest.fail("must refuse before installed read"))
    assert h.main(["verify", "--candidate", CANDIDATE, "--base", BASE]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_actual_unprivileged_path_ownership_check_refuses(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("this proof requires the unprivileged builder seat")
    file = tmp_path / "candidate-validator.py"
    file.write_text('print("PASS")')
    with pytest.raises(h.Refusal, match="replaceable"):
        h.protected(file)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("scripts/ci/gate.py", tarfile.SYMTYPE),
        ("hardlink", tarfile.LNKTYPE),
    ],
)
def test_candidate_archive_cannot_escape_into_trusted_tools(tmp_path, monkeypatch, name, kind):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = "/etc/fictional-secret"
        archive.addfile(entry)
    monkeypatch.setattr(
        h, "git", lambda _repo, *a: CANDIDATE.encode() if a[0] == "rev-parse" else raw.getvalue()
    )
    with pytest.raises(h.Refusal, match="unsafe"):
        h.snapshot(tmp_path, CANDIDATE, tmp_path / "snapshot")
    assert not (tmp_path / "escape").exists()


def test_existing_ci_keeps_live_evidence_on_alternate_merge_paths():
    # Source-only package must not remove the check from manual PRs, push-to-main,
    # or dispatch. It adds ac-ship protection, never authorizes retiring CI.
    workflow = (ROOT / ".github/workflows/migration-safety.yml").read_text()
    for text in [
        "pull_request:",
        "push:",
        "workflow_dispatch:",
        "Require governed schema artifact identity",
        "Download only the governed schema bundle",
        "--artifact-dir",
        "--manifest-sha256",
        "expired == false",
    ]:
        assert text in workflow
    assert "--baseline-from-migrations" not in workflow


def test_trusted_exporter_selected_outside_candidate(tmp_path, monkeypatch):
    source = tmp_path / "candidate"
    sentinel = tmp_path / "candidate-ran"
    for name in ["scripts/ops/export_migration_schema.py", "scripts/ci/migration_schema_gate.py"]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'open({str(sentinel)!r}, "w").write("credential stolen")')
    bundle = tmp_path / "trusted-install"
    calls = []

    def stop_after_export(argv, **kw):
        calls.append((argv, kw))
        raise h.Refusal("fictional stop before live export")

    monkeypatch.setattr(h, "command", stop_after_export)
    with pytest.raises(h.Refusal):
        h.rehearse(
            CONFIG | {"bundle": str(bundle)},
            source,
            tmp_path / "base",
            tmp_path / "pair",
            tmp_path / "socket",
        )
    assert calls[0][0][:3] == [
        sys.executable,
        "-IB",
        str(bundle / "scripts/ops/export_migration_schema.py"),
    ]
    assert not sentinel.exists()


def test_candidate_validator_is_never_imported(tmp_path):
    # Separate isolated interpreter proves import resolution without shared test
    # module caches. Trusted code here is fictional and raises no service calls.
    bundle, candidate = tmp_path / "trusted", tmp_path / "candidate"
    for root, content in [
        (bundle, "TRUSTED = True\n"),
        (candidate, 'raise RuntimeError("candidate imported")\n'),
    ]:
        p = root / "scripts/ci/migration_schema_gate.py"
        p.parent.mkdir(parents=True)
        p.write_text(content)
    code = (
        'import importlib.util; s=importlib.util.spec_from_file_location("h", '
        f"{str(Path(h.__file__))!r}); "
        f"h=importlib.util.module_from_spec(s); s.loader.exec_module(h); "
        f"assert h.load_gate(h.Path({str(bundle)!r})).TRUSTED"
    )
    subprocess.run(  # noqa: S603 - isolated interpreter with fictional fixture modules
        [sys.executable, "-IB", "-c", code],
        cwd=candidate,
        env={"PATH": os.defpath, "PYTHONPATH": str(candidate)},
        check=True,
    )


def test_candidate_pass_text_cannot_replace_exact_database_revision(tmp_path, monkeypatch):
    from types import SimpleNamespace

    pair = tmp_path / "pair"
    pair.mkdir()
    (pair / "manifest.json").write_text("{}")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *_):
            return self

        def fetchall(self):
            return [("wrong_revision",)]

    fake = SimpleNamespace()
    fake.rehearse = lambda _pair, _hash, _baseline, _chain, revision, source: fake.migrate(
        SimpleNamespace(connect=Connection), {}, source, "upgrade", revision
    )
    calls = []
    monkeypatch.setattr(h, "command", lambda *a, **kw: b"")
    monkeypatch.setattr(h, "load_gate", lambda _: fake)
    monkeypatch.setattr(h, "migration_scope", lambda *a: ("0127", "0128", [object()]))

    def docker(*argv, **kw):
        calls.append(argv)
        return b"schema-rehearsal: PASS (forged by candidate)"

    monkeypatch.setattr(h, "docker", docker)
    with pytest.raises(h.Refusal, match="exact requested revision"):
        h.rehearse(
            CONFIG | {"bundle": str(tmp_path)},
            tmp_path / "source",
            tmp_path / "base",
            pair,
            tmp_path / "sockets",
        )
    assert calls[0][0] == "run"
    assert calls[1][:2] == ("rm", "--force")


def test_timeout_kills_candidate_container_before_any_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace

    pair = tmp_path / "pair"
    pair.mkdir()
    (pair / "manifest.json").write_text("{}")
    fake = SimpleNamespace()
    fake.rehearse = lambda _pair, _hash, _baseline, _chain, revision, source: fake.migrate(
        object(), {}, source, "upgrade", revision
    )
    monkeypatch.setattr(h, "command", lambda *a, **kw: b"")
    monkeypatch.setattr(h, "load_gate", lambda _: fake)
    monkeypatch.setattr(h, "migration_scope", lambda *a: ("0127", "0128", [object()]))
    calls = []

    def docker(*argv, **kw):
        calls.append(argv)
        if argv[0] == "run":
            raise h.Refusal("fictional timeout")
        return b""

    monkeypatch.setattr(h, "docker", docker)
    with pytest.raises(h.Refusal, match="timeout"):
        h.rehearse(
            CONFIG | {"bundle": str(tmp_path)},
            tmp_path / "source",
            tmp_path / "base",
            pair,
            tmp_path / "sockets",
        )
    assert calls[1][:2] == ("rm", "--force")
    assert not list(tmp_path.glob("*.json"))


def test_real_container_adversarial_credential_and_socket_probe(tmp_path):
    """Root may run after approval with the reviewed offline image, never auto-pull."""
    image = os.environ.get("AC_TRUSTED_REHEARSAL_TEST_IMAGE")
    if not image:
        pytest.skip("requires approved Docker executor and pinned offline runner image")
    # A deliberately malicious module runs IN the candidate boundary and reports
    # only fictional assertions. It cannot replace the installed host harness.
    source, sockets = tmp_path / "candidate", tmp_path / "sockets"
    source.mkdir(mode=0o755)
    sockets.mkdir(mode=0o755)
    (source / "pyproject.toml").write_text(
        '[project]\nname="fictional-probe"\nversion="0.0.0"\nrequires-python=">=3.12"\n'
        "[tool.uv]\npackage=false\n"
    )
    # No dependencies or code are installed on the host. This is static lock data.
    (source / "uv.lock").write_text(
        'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n\n'
        '[[package]]\nname = "fictional-probe"\nversion = "0.0.0"\n'
        'source = { virtual = "." }\n'
    )
    (source / "alembic").mkdir()
    (source / "alembic/__init__.py").write_text("")
    (source / "alembic/__main__.py").write_text(
        "import os, pathlib, socket\n"
        "assert os.geteuid() == 65534\n"
        'assert "UNCLASSIFIED_SECRET" not in os.environ\n'
        'assert not pathlib.Path("/var/run/docker.sock").exists()\n'
        'assert not pathlib.Path("/run/ac-release/schema-rehearsal.key").exists()\n'
        'assert not pathlib.Path("/opt/ac-schema-rehearsal").exists()\n'
        'try:\n    socket.create_connection(("192.0.2.1", 443), timeout=1)\n'
        'except OSError:\n    pass\nelse:\n    raise AssertionError("network escaped")\n'
        'try:\n    pathlib.Path("/candidate/owned").write_text("attack")\n'
        'except OSError:\n    pass\nelse:\n    raise AssertionError("source mount writable")\n'
        'print("fictional-isolation-probe: PASS")\n'
    )
    name = "ac-rehearsal-probe-" + h.uuid4().hex
    try:
        output = h.docker(
            *h.worker_argv(source, sockets, image, name, "upgrade", "0128"), timeout=120
        )
        assert b"fictional-isolation-probe: PASS" in output
        assert not (source / "owned").exists()
    finally:
        h.docker("rm", "--force", "--volumes", name, timeout=30)
