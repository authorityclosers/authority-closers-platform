"""Offline release executor protocol, failure recovery and default-local parity."""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.infra.test_ac_release import HEAD, MODULE, OLD, OUTSIDE, make_engine, promotion_setup

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("remote_tests", ROOT / "infra/release/ac_remote.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
HOST = "production.example.invalid"
CONTROLLER = "e" * 40


class Backend:
    def __init__(self):
        self.pair = {"core": OLD, "web": OUTSIDE}
        self.backup_present = True
        self.installs = 0
        self.prepares = 0
        self.boot = "boot-one"
        self.crash = False
        self.canary_pass = True

    def boot_id(self):
        return self.boot

    def status(self):
        return {
            "pair": dict(self.pair),
            "web_image": "sha256:" + "d" * 64,
            "native_sha": None,
            "backup_receipt": "f" * 64 if self.backup_present else None,
            "units_path": "/native/units.json",
            "units_digest": "f" * 64,
            "migration_heads": {OLD: "20260929_0052", HEAD: "20260929_0052"},
            "approval_expires": None,
            "restore_evidence": None,
            "web_rollback": None,
        }

    def prepare(self, request, directory):
        self.prepares += 1
        assert (directory / "repository.bundle").is_file()
        return {"verified": True}

    def require_backup(self, pair):
        if not self.backup_present:
            raise R.RemoteError("missing backup")

    def install(self, request):
        self.installs += 1
        if not request["dry_run"] and not request["native"]:
            self.pair[request["component"]] = request["sha"]
        if self.crash:
            raise KeyboardInterrupt  # Simulated power loss bypasses failure receipt finalisation.
        return {"previous": request["expected"][request["component"]]}

    def backup(self, request):
        self.backup_present = True
        return {"verified": True, "path": "/remote/backup.dump", "sha256": "f" * 64, "bytes": 3}

    def canary(self, request):
        if request["pair"] != self.pair or not self.canary_pass:
            raise R.RemoteError("canary failed")
        return {"result": "pass"}


class Transport:
    def __init__(self, executor):
        self.executor = executor
        self.calls = []
        self.corrupt = False
        self.move = False
        self.drop = False

    def upload(self, request_id, path):
        target = self.executor.root / "incoming" / (request_id + ".tar")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if self.corrupt:
            with target.open("ab") as stream:
                stream.write(b"corrupt")
        if self.move:
            self.executor.backend.pair["core"] = "c" * 40

    def call(self, verb, request):
        self.calls.append((verb, copy.deepcopy(request)))
        result = self.executor.handle(verb, request)
        if self.drop and verb in {"install", "rollback-app"}:
            self.drop = False
            raise R.RemoteError("connection lost after commit")
        return result


@pytest.fixture
def remote(tmp_path):
    engine = make_engine(tmp_path / "coordinator")
    build = MODULE.Build(HEAD, 100, 7, "core-" + HEAD, "sha256:" + "a" * 64)
    bundle = engine.paths.store / HEAD / "core"
    bundle.mkdir(parents=True)
    for name in MODULE.CORE_FILES:
        (bundle / name).write_bytes((name + "\n").encode())
    (bundle.parent / "core.provenance.json").write_text(
        json.dumps({"artifact_digest": build.artifact_digest})
    )
    engine.store_bundle = lambda *_: bundle
    engine.keep_native_build = lambda *_: None
    engine.installed_engine = lambda: CONTROLLER

    def runner(argv, **kwargs):
        assert argv[0] == "git" and "bundle" in argv
        Path(argv[-2]).write_bytes(b"offline Git fixture")
        return subprocess.CompletedProcess(argv, 0, "", "")

    engine.run = runner
    backend = Backend()
    executor = R.Executor(backend, HOST, tmp_path / "host")
    transport = Transport(executor)
    client = R.Client(engine, HOST, transport)
    return engine, backend, executor, transport, client, build


def prepared(remote, **overrides):
    _, _, executor, transport, client, build = remote
    client.deploy("core", build, dry_run=True, **overrides)
    request = next(request for verb, request in transport.calls if verb == "prepare")
    return executor, request


def test_same_artifact_bytes_and_receipts(remote):
    engine, backend, executor, transport, client, build = remote
    result = client.deploy("core", build, dry_run=False)
    assert backend.pair == {"core": HEAD, "web": OUTSIDE}
    assert backend.installs == 1
    request = next(value for verb, value in transport.calls if verb == "prepare")
    directory = executor.root / "requests" / request["request_id"]
    for name in MODULE.CORE_FILES:
        original = engine.paths.store / HEAD / "core" / name
        copied = directory / "store" / HEAD / "core" / name
        assert original.read_bytes() == copied.read_bytes()
        assert request["digests"][f"store/{HEAD}/core/{name}"] == R.digest(original)
    receipt = R.load(executor.receipt_path(result["remote_request_id"]))
    assert receipt["target"] == HOST and receipt["digests"] == request["digests"]
    assert receipt["finished_at"] >= receipt["started_at"]
    assert receipt["boot_id"] == "boot-one" and receipt["result"] == "committed"


@pytest.mark.parametrize("fault", ["move", "corrupt"])
def test_stale_predecessor_and_corrupt_transport_are_refused(remote, fault):
    _, backend, _, transport, client, build = remote
    setattr(transport, fault, True)
    with pytest.raises(R.RemoteError, match="preparation refused"):
        client.deploy("core", build, dry_run=False)
    assert backend.installs == backend.prepares == 0


def test_coordinator_predecessor_is_pinned_to_admission(remote):
    engine, backend, _, _, client, build = remote
    engine._remote_expected_pair = dict(backend.pair)
    backend.pair["core"] = "c" * 40
    with pytest.raises(R.RemoteError, match="stale production predecessor"):
        client.deploy("core", build, dry_run=False)
    assert backend.installs == 0


def test_missing_backup_refuses_before_installer(remote):
    _, backend, executor, transport, client, build = remote
    backend.backup_present = False
    with pytest.raises(R.RemoteError, match="unknown or refused"):
        client.deploy("core", build, dry_run=False)
    assert backend.installs == 0
    assert any(R.load(p)["result"] == "failed" for p in (executor.root / "receipts").glob("*"))
    assert not any(verb == "rollback-app" for verb, _ in transport.calls)


def test_lost_response_after_commit_is_read_back_without_replay(remote):
    _, backend, _, transport, client, build = remote
    transport.drop = True
    result = client.deploy("core", build, dry_run=False)
    assert result["remote_request_id"] and backend.installs == 1
    assert [v for v, _ in transport.calls].count("install") == 1
    assert not any(v == "rollback-app" for v, _ in transport.calls)


def test_duplicate_request_is_idempotent_across_executor_restart(remote):
    _, backend, executor, transport, client, build = remote
    client.deploy("core", build, dry_run=False)
    request = next(r for v, r in transport.calls if v == "install")
    receipt = executor.handle("install", request)
    restarted = R.Executor(backend, HOST, executor.root)
    assert restarted.handle("install", request) == receipt
    assert backend.installs == 1
    changed = {**request, "sha": OLD}
    with pytest.raises(R.RemoteError, match="reused"):
        restarted.handle("install", changed)


def test_host_restart_leaves_unknown_and_blocks_new_install(remote):
    _, backend, executor, _, client, build = remote
    backend.crash = True
    with pytest.raises(KeyboardInterrupt):
        client.deploy("core", build, dry_run=False)
    backend.boot = "boot-two"
    backend.crash = False
    receipt_path = next((executor.root / "receipts").glob("*"))
    request_id = receipt_path.stem
    status = executor.handle(
        "status", {"target": HOST, "request_id": "9" * 32, "lookup": request_id}
    )
    assert status["data"]["receipt"]["result"] == "unknown"
    assert status["data"]["receipt"]["boot_id"] == "boot-one"
    with pytest.raises(R.RemoteError, match="preparation refused"):
        client.deploy("core", build, dry_run=False)
    assert backend.installs == 1


def test_restart_with_prepared_receipt_does_not_skip_predecessor_check(remote):
    _, backend, executor, transport, client, build = remote
    original = transport.call

    def drop_before_install(verb, request):
        if verb == "install":
            raise R.RemoteError("disconnected before dispatch")
        return original(verb, request)

    transport.call = drop_before_install
    with pytest.raises(R.RemoteError):
        client.deploy("core", build, dry_run=False)
    request = next(r for v, r in transport.calls if v == "prepare")
    backend.boot = "restarted"
    backend.pair["web"] = "d" * 40
    result = R.Executor(backend, HOST, executor.root).handle("install", request)
    assert result["result"] == "failed" and backend.installs == 0


@pytest.mark.parametrize("kind", ["hash", "missing", "symlink", "traversal", "duplicate"])
def test_member_inventory_rejects_unsafe_or_corrupt_files(remote, kind):
    _, backend, executor, transport, client, build = remote
    original_upload = transport.upload

    def upload(request_id, path):
        original_upload(request_id, path)
        remote_path = executor.root / "incoming" / (request_id + ".tar")
        # Re-hash the envelope so only the member-level gate can catch this.
        request_path = client.engine.paths.state / "remote-requests" / request_id / "request.json"
        request = R.load(request_path)
        with tarfile.open(remote_path) as archive:
            members = [(m.name, archive.extractfile(m).read()) for m in archive]
        with tarfile.open(remote_path, "w") as archive:
            for i, (name, content) in enumerate(members):
                if i == 0 and kind == "missing":
                    continue
                member = tarfile.TarInfo("../escape" if i == 0 and kind == "traversal" else name)
                if i == 0 and kind == "hash":
                    content += b"bad"
                member.size = len(content)
                if i == 0 and kind == "symlink":
                    member.type, member.linkname = tarfile.SYMTYPE, "/etc/shadow"
                archive.addfile(member, io.BytesIO(content))
                if i == 0 and kind == "duplicate":
                    archive.addfile(member, io.BytesIO(content))
        request["payload_sha256"] = R.digest(remote_path)
        # Client has already loaded its request; alter the outgoing envelope only.
        transport.new_hash = request["payload_sha256"]

    original_call = transport.call

    def call(verb, request):
        if verb == "prepare":
            request = {**request, "payload_sha256": transport.new_hash}
        return original_call(verb, request)

    transport.upload, transport.call = upload, call
    with pytest.raises(R.RemoteError, match="preparation refused"):
        client.deploy("core", build, dry_run=False)
    assert backend.installs == backend.prepares == 0
    assert not (executor.root / "escape").exists()


@pytest.mark.parametrize("schema_equal", [True, False])
def test_application_rollback_reuses_reviewed_controller_without_database_restore(
    tmp_path, schema_equal
):
    events = []
    engine = SimpleNamespace(
        stored_build=lambda *_: SimpleNamespace(sha=OLD, artifact_digest="sha256:" + "a" * 64),
        migration_head=lambda sha: (
            "20260929_0052" if schema_equal or sha == OLD else "20260930_0061"
        ),
        deploy_core=lambda *args, **kw: events.append((args, kw)) or {"previous": HEAD},
        record=lambda entry: events.append(entry),
    )
    backend = R.HostBackend(engine, tmp_path)
    request = {
        "sha": OLD,
        "artifact_digest": "sha256:" + "a" * 64,
        "component": "core",
        "native": False,
        "rollback": True,
        "expected": {"core": HEAD, "web": HEAD},
        "dry_run": False,
    }
    if schema_equal:
        backend.install(request)
        assert events[0] == (
            ("production", engine.stored_build()),
            {"dry_run": False, "rollback_only": True},
        )
    else:
        with pytest.raises(R.RemoteError, match="schema changed"):
            backend.install(request)
        assert events == []


@pytest.mark.parametrize("pass_canary", [True, False])
def test_failed_canary_cannot_record_promotion(tmp_path, pass_canary):
    engine, _, core, web = promotion_setup(tmp_path)
    remote = SimpleNamespace()

    def operation(verb, **fields):
        assert verb == "canary" and fields == {"pair": {"core": HEAD, "web": HEAD}}
        if not pass_canary:
            raise R.RemoteError("failed canary")
        return {"result": "pass"}

    remote.operation = operation
    engine.remote_target = lambda *_: remote

    def attempt(environment, component, build, **kwargs):
        (core if component == "core" else web)[environment] = build.sha
        return {"result": "success"}

    engine.attempt = attempt
    if pass_canary:
        engine.promote("patch", "v0.2.1", requested_by="cli:operator", trigger="cli")
        assert engine.release_records()[-1]["core_sha"] == HEAD
    else:
        with pytest.raises(MODULE.ReleaseError, match="unknown"):
            engine.promote("patch", "v0.2.1", requested_by="cli:operator", trigger="cli")
        assert engine.release_records() == [] and engine.is_paused("production")


@pytest.mark.parametrize("config", [{}, {"staging": "local", "production": "local"}])
def test_default_target_map_leaves_staging_and_production_local(tmp_path, config):
    engine = make_engine(tmp_path)
    (engine.paths.config / "targets.json").write_text(json.dumps(config))
    assert engine.remote_target("staging") is engine.remote_target("production") is None


@pytest.mark.parametrize(
    "config",
    [
        {"staging": "remote:other.invalid"},
        {"production": "remote:host;id"},
        {"production": "remote:host.invalid"},
        {"production": "bogus"},
        {"unexpected": "local"},
    ],
)
def test_invalid_target_map_fails_closed(tmp_path, config):
    engine = make_engine(tmp_path)
    (engine.paths.config / "targets.json").write_text(json.dumps(config))
    with pytest.raises(MODULE.ReleaseError, match="configuration"):
        engine.remote_target()


def test_production_hooks_do_not_run_local_installers(tmp_path):
    engine = make_engine(tmp_path)
    calls = []
    remote = SimpleNamespace(
        status=lambda: {**Backend().status(), "web_rollback": None},
        deploy=lambda *a, **kw: calls.append((a, kw)) or {},
        operation=lambda *a, **kw: Backend().backup({}),
    )
    engine.remote_target = lambda environment="production": (
        remote if environment == "production" else None
    )
    build = SimpleNamespace(sha=HEAD)
    engine.deploy_core("production", build)
    engine.deploy_web("production", build, dry_run=True)
    assert len(calls) == 2 and engine.run.calls == []
    assert engine.current_core("production") == OLD
    assert engine.current_web("production")[0] == OUTSIDE
    assert engine.migration_head(OLD) == "20260929_0052"
    assert engine.restore_check_evidence() is None
    engine.train_dump()
    assert engine._remote_dump == {"path": "/remote/backup.dump", "sha256": "f" * 64, "bytes": 3}


def test_ssh_always_pins_identity_host_key_and_disables_forwarding(monkeypatch, tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"{}", b"")

    monkeypatch.setattr(R.subprocess, "run", run)
    ssh = R.SSH(HOST, "/key", "/known_hosts")
    ssh.call("status", {})
    ssh.upload("a" * 32, tmp_path / "payload.tar")
    for argv, _ in calls:
        joined = " ".join(argv)
        assert "StrictHostKeyChecking=yes" in joined and "UserKnownHostsFile=/known_hosts" in joined
        assert "ClearAllForwardings=yes" in joined and "ForwardAgent=no" in joined
        assert "IdentitiesOnly=yes" in joined and "-F /dev/null" in joined
    assert "-O" in calls[1][0]
    with pytest.raises(R.RemoteError):
        ssh.call("shell", {})
    assert len(calls) == 2


@pytest.mark.parametrize(
    "command", ["bash", "scp -r -t /etc", "scp -t /etc/passwd", "scp -t /tmp/../etc/file"]
)
def test_forced_scp_has_no_arbitrary_write_or_shell(tmp_path, command):
    with pytest.raises(R.RemoteError, match="forced command"):
        R.receive_scp(command, tmp_path, io.BytesIO(), io.BytesIO())
    assert not list(tmp_path.iterdir())


def test_scp_single_file_is_bounded_and_cannot_replace(tmp_path):
    command = f"scp -t {tmp_path}/incoming/{'a' * 32}.tar"
    content = b"C0644 3 payload.tar\nabc\0"
    out = io.BytesIO()
    R.receive_scp(command, tmp_path, io.BytesIO(content), out)
    assert out.getvalue() == b"\0\0\0"
    assert (tmp_path / "incoming" / ("a" * 32 + ".tar")).read_bytes() == b"abc"
    destination = tmp_path / "incoming" / ("a" * 32 + ".tar")
    inode = destination.stat().st_ino
    R.receive_scp(command, tmp_path, io.BytesIO(content), io.BytesIO())
    assert destination.stat().st_ino == inode
    with pytest.raises(R.RemoteError, match="different bytes"):
        R.receive_scp(command, tmp_path, io.BytesIO(b"C0644 3 payload.tar\nxyz\0"), io.BytesIO())
    assert destination.read_bytes() == b"abc"
    assert not list((tmp_path / "incoming").glob(".*"))


def test_all_other_executor_verbs_are_refused(remote):
    _, _, executor, _, _, _ = remote
    for verb in ("shell", "sudo", "restore-db", "reboot"):
        with pytest.raises(R.RemoteError):
            executor.handle(verb, {"target": HOST, "request_id": "a" * 32})


def legacy_tree():
    """Strip ONLY opt-in additions; pin the remaining Engine to today's source."""
    tree = ast.parse((ROOT / "infra/release/ac_release.py").read_text())
    engine = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Engine")
    engine.body = [
        n
        for n in engine.body
        if getattr(n, "name", "") not in {"remote_target", "remote_call", "remote_operation"}
    ]

    class RemoveRemote(ast.NodeTransformer):
        def visit_If(self, node):
            test = ast.unparse(node.test)
            if test == "remote is not None" or test == "self.remote_target() is not None":
                return None
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if any(isinstance(t, ast.Name) and t.id == "remote" for t in node.targets):
                return None
            return self.generic_visit(node)

        def visit_IfExp(self, node):
            if ast.unparse(node.test) == "self.remote_target() is not None":
                return node.orelse
            return self.generic_visit(node)

    RemoveRemote().visit(engine)
    # Independent fingerprint of the pre-change Engine (source c0b46d87b blob).
    assert (
        hashlib.sha256(ast.dump(engine).encode()).hexdigest()
        == "493f9c2e39e8fc24742bdf2d0bea99cc61f3be4278d31bc6c9bbb1c3444556f8"
    )
    return ast.fix_missing_locations(tree)


@pytest.mark.parametrize("explicit_local", [False, True])
def test_local_behavior_matches_pre_change_byte_for_byte(tmp_path, monkeypatch, explicit_local):
    tree = legacy_tree()
    legacy = type(MODULE)("legacy_remote_parity")
    legacy.__file__ = str(ROOT / "infra/release/ac_release.py")
    monkeypatch.setitem(sys.modules, legacy.__name__, legacy)
    exec(compile(tree, legacy.__file__, "exec"), legacy.__dict__)  # noqa: S102 - pinned trusted AST
    monkeypatch.setattr(MODULE, "_now", lambda: "2026-10-29T00:00:00Z")
    monkeypatch.setattr(legacy, "_now", lambda: "2026-10-29T00:00:00Z")
    traces = []
    for i, cls in enumerate((MODULE.Engine, legacy.Engine)):
        home = tmp_path / str(i)
        engine, runner, _, _ = promotion_setup(home)
        engine.__class__ = cls
        engine.clock = lambda: 1793232000
        if explicit_local:
            (engine.paths.config / "targets.json").write_text(
                '{"staging":"local","production":"local"}'
            )
        engine.attempt = lambda env, component, build, **kw: {
            "result": "success",
            "component": component,
        }
        result = engine.promote("patch", "v0.2.1", requested_by="cli:operator", trigger="cli")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            MODULE._print(engine.status(), True)
        traces.append(
            R.encoded(
                {
                    "result": result,
                    "stdout": output.getvalue(),
                    "commands": runner.calls,
                    "ledger": engine.paths.releases.read_text(),
                    "history": engine.paths.history.read_text(),
                }
            ).replace(str(home).encode(), b"<root>")
        )
    assert traces[0] == traces[1]


def test_real_git_bundle_and_store_are_imported_without_network_or_build(tmp_path):
    repository = tmp_path / "source"
    repository.mkdir()
    commands = [
        ["init", "-q", "-b", "main"],
        ["config", "user.name", "Fixture"],
        ["config", "user.email", "fixture@example.invalid"],
    ]
    for args in commands:
        subprocess.run(["/usr/bin/git", "-C", str(repository), *args], check=True)  # noqa: S603
    (repository / "source.txt").write_bytes(b"source only")
    for args in [["add", "."], ["commit", "-q", "-m", "fixture"]]:
        subprocess.run(["/usr/bin/git", "-C", str(repository), *args], check=True)  # noqa: S603
    directory = tmp_path / "payload"
    directory.mkdir()
    subprocess.run(  # noqa: S603 - synthetic local Git only
        [
            "/usr/bin/git",
            "-C",
            str(repository),
            "bundle",
            "create",
            str(directory / "repository.bundle"),
            "--all",
        ],
        check=True,
    )
    artifact = directory / "store" / HEAD / "core" / "application-images.tar.gz"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"exact CI image transport")
    engine = make_engine(tmp_path / "engine")
    shutil.rmtree(engine.paths.mirror)
    engine.installed_engine = lambda: CONTROLLER
    calls = []

    def run(argv, **kwargs):
        assert argv[0] == "git" and not any("http" in a for a in argv)
        assert "docker" not in argv and "build" not in argv
        calls.append(argv)
        return MODULE.run_command(argv, **kwargs)

    engine.run = run
    backend = R.HostBackend(engine, tmp_path / "host")
    backend.prepare({"controller": CONTROLLER}, directory)
    assert (
        artifact.read_bytes()
        == (engine.paths.store / HEAD / "core/application-images.tar.gz").read_bytes()
    )
    subprocess.run(  # noqa: S603 - synthetic local Git only
        ["/usr/bin/git", f"--git-dir={engine.paths.mirror}", "cat-file", "-e", "main:source.txt"],
        check=True,
    )
    backend.prepare({"controller": CONTROLLER}, directory)
    artifact.write_bytes(b"different")
    with pytest.raises(R.RemoteError, match="immutable"):
        backend.prepare({"controller": CONTROLLER}, directory)
    with pytest.raises(R.RemoteError, match="controller"):
        backend.prepare({"controller": HEAD}, directory)


@pytest.mark.parametrize("fault", ["missing", "stale", "corrupt", "predecessor", "ok"])
def test_host_backup_gate_validates_bytes_age_and_predecessor(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(R.time, "time", lambda: 2000)
    engine = SimpleNamespace()
    backend = R.HostBackend(engine, tmp_path)
    dump = tmp_path / "backup.dump"
    dump.write_bytes(b"backup bytes")
    data = {"path": str(dump), "sha256": R.digest(dump), "at": 1990, "cores": [OLD]}
    if fault == "stale":
        data["at"] = 0
    if fault == "corrupt":
        data["sha256"] = "0" * 64
    if fault == "predecessor":
        data["cores"] = [HEAD]
    if fault != "missing":
        R.save(tmp_path / "backup.json", data)
    if fault == "ok":
        backend.require_backup({"core": OLD, "web": OUTSIDE})
    else:
        with pytest.raises(R.RemoteError):
            backend.require_backup({"core": OLD, "web": OUTSIDE})


def test_backup_capture_and_failed_canary_host_adapters(tmp_path):
    dump = tmp_path / "backup.dump"
    dump.write_bytes(b"verified dump")
    calls = []
    engine = SimpleNamespace(
        train_dump=lambda: str(dump),
        current_core=lambda *_: OLD,
        train_disk_check=lambda: calls.append("disk"),
        run=lambda argv, **kw: (
            calls.append(argv) or subprocess.CompletedProcess(argv, 0, "failed\n", "")
        ),
    )
    backend = R.HostBackend(engine, tmp_path)
    proof = backend.backup({"target": HOST, "request_id": "a" * 32})
    assert proof["sha256"] == R.digest(dump) and proof["bytes"] == len(b"verified dump")
    backend.backup({"target": HOST, "request_id": "b" * 32, "check_only": True})
    assert calls == ["disk"]
    pair = {"core": OLD, "web": OUTSIDE}
    backend.status = lambda: {"pair": pair}
    with pytest.raises(R.RemoteError, match="canary failed"):
        backend.canary({"target": HOST, "request_id": "c" * 32, "pair": pair})
    assert calls[1:] == [
        ["systemctl", "start", "ac-canary@production.service"],
        ["systemctl", "show", "ac-canary@production.service", "-p", "Result", "--value"],
    ]


def test_native_preparation_uses_host_units_and_no_runtime_install(tmp_path):
    units = tmp_path / "native-units.json"
    units.write_text("{}")
    calls = []
    engine = SimpleNamespace(
        stored_build=lambda *_: SimpleNamespace(sha=HEAD, artifact_digest="sha256:" + "a" * 64),
        prepare_native=lambda *a, **kw: calls.append((a, kw)) or {"runtime_mutation": False},
    )
    backend = R.HostBackend(engine, tmp_path)
    backend.units = lambda: units
    request = {
        "sha": HEAD,
        "artifact_digest": "sha256:" + "a" * 64,
        "component": "core",
        "native": True,
        "units_digest": R.digest(units),
        "dry_run": False,
    }
    assert backend.install(request) == {"runtime_mutation": False}
    assert calls == [(("production", HEAD, units, R.digest(units)), {"dry_run": False})]
    units.write_text('{"changed":true}')
    with pytest.raises(R.RemoteError, match="predecessor changed"):
        backend.install(request)
    assert len(calls) == 1


def test_ship_patch_preserves_all_staging_commands_and_gates(tmp_path):
    # Check the reviewed patch against the pinned source copy only when available;
    # CI verifies its exact hunks, production routing and shell syntax independently.
    patch = (ROOT / "infra/release/remote/ac-ship.patch").read_text()
    removed = [
        line[1:]
        for line in patch.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    assert removed == []  # Production dispatch wraps existing commands; no gate is removed.
    assert "PRODUCTION_MODE=$(/usr/local/sbin/ac-release production-target) || fail" in patch
    assert 'remote-op prepare-native --sha "$target"' in patch
    assert "remote-op backup" in patch and "remote-op canary" in patch
    assert "systemctl start ac-canary@staging.service" not in patch


def test_coordinator_receipt_identity_must_match_request(remote):
    _, _, _, transport, client, _ = remote
    original = transport.call

    def wrong(verb, request):
        result = original(verb, request)
        return {**result, "target": "other.example.invalid"}

    transport.call = wrong
    with pytest.raises(R.RemoteError, match="identity"):
        client.status()


@pytest.mark.parametrize("fault", ["ok", "opaque", "wrong_release", "bad_hash", "wrong_path"])
def test_supervised_snapshot_fallback_requires_structured_fresh_proof(tmp_path, monkeypatch, fault):
    import os

    monkeypatch.setattr(R.time, "time", lambda: 2000)
    backups = tmp_path / "backups/application/production"
    directory = tmp_path / "backups/production-snapshots/fixture"
    directory.mkdir(parents=True)
    dump = directory / "backup.dump"
    dump.write_bytes(b"full snapshot")
    os.utime(dump, (2000, 2000))
    metadata = {
        "release_id": HEAD if fault == "wrong_release" else OLD,
        "environment": "production",
        "dump_sha256": "0" * 64 if fault == "bad_hash" else R.digest(dump),
        "dump_bytes": dump.stat().st_size,
        "verification": "pg_restore --list",
    }
    R.save(directory / "metadata.json", metadata)
    proof = {
        "upload_download_decrypt": "passed",
        "environment": "production",
        "metadata": "same_exported_snapshot",
        "local_snapshot": str(tmp_path if fault == "wrong_path" else directory),
    }
    calls = []

    def bounded():
        raise MODULE.ReleaseError("bounded dump refused")

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, "opaque path" if fault == "opaque" else json.dumps(proof), ""
        )

    engine = SimpleNamespace(
        paths=SimpleNamespace(backups=backups),
        train_dump=bounded,
        current_core=lambda *_: OLD,
        run=run,
    )
    backend = R.HostBackend(engine, tmp_path / "executor")
    request = {"target": HOST, "request_id": "a" * 32}
    # The train never falls back to a weaker/different backup contract.
    with pytest.raises(MODULE.ReleaseError):
        backend.backup(request)
    assert calls == []
    if fault == "ok":
        result = backend.backup({**request, "supervised": True})
        assert result["verified"] and result["sha256"] == R.digest(dump)
    else:
        with pytest.raises((R.RemoteError, ValueError)):
            backend.backup({**request, "supervised": True})
        assert not (backend.root / "backup.json").exists()
    assert calls == [["/usr/local/sbin/ac-db-snapshot", "production", "before-remote", "--execute"]]


@pytest.mark.parametrize("valid", [True, False])
def test_host_train_smoke_uses_existing_scope_and_exact_tuple(tmp_path, valid):
    pair = {"core": HEAD, "web": HEAD}
    calls = []

    @contextlib.contextmanager
    def source(sha):
        assert sha == HEAD
        yield tmp_path

    engine = SimpleNamespace(
        train_source=source,
        train_smoke=lambda *a, **kw: (
            calls.append((a, kw)) or {"result": "pass", "digest": "f" * 64}
        ),
    )
    backend = R.HostBackend(engine, tmp_path)
    backend.status = lambda: {"pair": pair if valid else {"core": OLD, "web": HEAD}}
    request = {
        "target": HOST,
        "request_id": "a" * 32,
        "pair": pair,
        "mode": "smoke",
        "reuse": False,
    }
    if valid:
        assert backend.canary(request)["result"] == "pass"
        assert calls == [(("production", (HEAD, HEAD), tmp_path), {"reuse": False})]
    else:
        with pytest.raises(R.RemoteError, match="tuple changed"):
            backend.canary(request)
        assert calls == []


@pytest.mark.parametrize(
    "field", ["dry_run", "rollback", "native", "controller", "sha", "expected"]
)
def test_malformed_manifest_is_refused_before_install(remote, field):
    _, backend, executor, transport, client, build = remote
    client.deploy("core", build, dry_run=True)
    request = next(r for v, r in transport.calls if v == "prepare")
    request = {
        **request,
        "request_id": "8" * 32,
        field: "invalid" if field not in {"dry_run", "rollback", "native"} else 1,
    }
    response = executor.handle("prepare", request)
    assert response["result"] == "failed" and backend.installs == 1


def test_different_admitted_artifact_cannot_reuse_stored_bytes(remote):
    engine, backend, _, _, client, build = remote
    (engine.paths.store / HEAD / "core.provenance.json").write_text(
        json.dumps({"artifact_digest": "sha256:" + "b" * 64})
    )
    with pytest.raises(R.RemoteError, match="provenance"):
        client.deploy("core", build, dry_run=False)
    assert backend.installs == backend.prepares == 0


def test_verified_backup_allows_operator_retry_after_precommit_refusal(remote):
    _, backend, _, _, client, build = remote
    backend.backup_present = False
    with pytest.raises(R.RemoteError):
        client.deploy("core", build, dry_run=False)
    assert backend.installs == 0
    backend.backup_present = True
    # A fresh backup changes the admitted request identity; no failed ID is replayed.
    result = client.deploy("core", build, dry_run=False)
    assert result["remote_request_id"] and backend.installs == 1


@pytest.mark.parametrize(("dry_run", "native"), [(True, False), (False, True)])
def test_failed_rehearsal_or_native_preparation_does_not_claim_runtime_unknown(
    remote, dry_run, native
):
    _, backend, executor, _, client, build = remote
    original = backend.install

    def refuse(request):
        raise R.RemoteError("native transition needs preparation")

    backend.install = refuse
    with pytest.raises(R.RemoteError):
        client.deploy(
            "core", build, dry_run=dry_run, native=native, units_digest="f" * 64 if native else None
        )
    assert all(R.load(p)["result"] == "failed" for p in (executor.root / "receipts").glob("*"))
    backend.install = original
    client.deploy("core", build, dry_run=False)
    assert backend.installs == 1
