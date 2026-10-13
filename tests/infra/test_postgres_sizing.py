"""Fictional admission, bounded output, redaction and process ownership proofs."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import select
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/vps-foundation/scripts/ac-postgres-sizing.py"
SPEC = importlib.util.spec_from_file_location("ac_postgres_sizing", SCRIPT)
assert SPEC and SPEC.loader
sizing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sizing)
SMALL_TABLES = ("alembic_version", "fictional_records")


@pytest.fixture
def backup(tmp_path):
    # Read the exact already approved Git object; never fetch or use the live backup edits.
    result = subprocess.run(  # noqa: S603 - exact local controlled source object
        [
            shutil.which("git"),
            "show",
            f"{sizing.APP_SHA}:infra/vps-foundation/scripts/ac-postgres-backup.py",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    source = tmp_path / "backup.py"
    source.write_bytes(result.stdout)
    return sizing.load_backup(source)


@pytest.fixture
def host(tmp_path, backup):
    release = tmp_path / "srv/authority-closers/application/releases" / sizing.APP_SHA
    (release / "environments").mkdir(parents=True)
    (release / "compose.yaml").write_text("name: ${AC_COMPOSE_PROJECT}\n")
    (release / "release-images.env").write_text(
        f"AC_RELEASE_ID={sizing.APP_SHA}\nAC_MIGRATION_HEAD={sizing.SCHEMA_HEAD}\n"
    )
    (release / "environments/production.env").write_bytes(
        (ROOT / "infra/application/environments/production.env").read_bytes()
    )
    manifest = release / "RELEASE-FILES.sha256"
    manifest.write_text(
        "".join(
            f"{sizing.sha256(p.read_bytes())}  ./{p.relative_to(release)}\n"
            for p in sorted(release.rglob("*"))
            if p.is_file()
        )
    )
    (release.parent.parent / "current-production").symlink_to(release)
    (tmp_path / "srv/authority-closers/state/application/production").mkdir(parents=True)
    scope = tmp_path / "var/lib/authority-closers/foundation-scopes"
    scope.mkdir(parents=True)
    (scope / "backup.release").write_text(f"foundation-{sizing.APP_SHA}\n")
    policy = tmp_path / f"srv/authority-closers/releases/foundation-{sizing.APP_SHA}/config/r2"
    policy.mkdir(parents=True)
    (policy / "free-tier-policy.conf").write_bytes(
        (ROOT / "infra/vps-foundation/config/r2/free-tier-policy.conf").read_bytes()
    )
    return tmp_path


def output(tables=SMALL_TABLES):
    return [
        {
            "kind": "database",
            "started_at": "2026-10-13T00:00:00.000000Z",
            "database_bytes": 1000000,
            "postgres_version_num": sizing.POSTGRES_VERSION_NUM,
            "read_only": True,
        },
        *(
            {
                "kind": "relation",
                "relation": t,
                "heap_bytes": 8192,
                "index_bytes": 8192,
                "total_bytes": 16384,
                "parity_count": 2,
            }
            for t in tables
        ),
        {"kind": "end", "finished_at": "2026-10-13T00:00:01.000000Z"},
    ]


def encoded(records):
    return ("1\n1\n" + "\n".join(json.dumps(r) for r in records) + "\n").encode()


def test_exact_approved_inventory_and_admission(backup, host):
    tables = sizing.inventory(backup)
    assert len(tables) == 149
    assert backup.parity_contract_for_head(sizing.SCHEMA_HEAD) == sizing.PARITY_CONTRACT
    assert sizing.admit(backup, "production", host).migration_head == sizing.SCHEMA_HEAD
    assert (
        sizing.sha256(
            sizing.bounded_file(
                host
                / f"srv/authority-closers/releases/foundation-{sizing.APP_SHA}"
                / "config/r2/free-tier-policy.conf"
            )
        )
        == sizing.POLICY_SHA256
    )


@pytest.mark.parametrize("drift", ["scope", "policy", "release", "profile"])
def test_release_scope_policy_and_manifest_drift_fail_closed(backup, host, drift):
    release = host / f"srv/authority-closers/application/releases/{sizing.APP_SHA}"
    paths = {
        "scope": host / "var/lib/authority-closers/foundation-scopes/backup.release",
        "policy": host
        / f"srv/authority-closers/releases/foundation-{sizing.APP_SHA}"
        / "config/r2/free-tier-policy.conf",
        "release": release / "release-images.env",
        "profile": release / "environments/production.env",
    }
    paths[drift].write_text("changed\n")
    with pytest.raises((sizing.Refusal, backup.BackupError)):
        sizing.admit(backup, "production", host)


def test_loader_never_executes_unreviewed_backup_source(tmp_path):
    sentinel = tmp_path / "executed"
    source = tmp_path / "unsafe.py"
    source.write_text(f"open({str(sentinel)!r}, 'w').close()")
    with pytest.raises(sizing.Refusal, match="backup_drift"):
        sizing.load_backup(source)
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "tables",
    [
        (),
        ("alembic_version", "bad';DELETE"),
        ("alembic_version", "alembic_version"),
        tuple(f"table_{i}" for i in range(1025)),
    ],
)
def test_inventory_bounds_and_unsafe_identifiers(tables):
    with pytest.raises(sizing.Refusal, match="inventory_drift"):
        sizing.fixed_sql(tables)


def test_sql_and_command_have_fixed_bounds_and_runtime_secret_injection(backup, host):
    target = sizing.admit(backup, "production", host)
    sql = sizing.fixed_sql(sizing.inventory(backup)).decode()
    assert sql.count("BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;") == 1
    assert "SET LOCAL lock_timeout = '1000ms'" in sql
    assert "SET LOCAL statement_timeout = '10000ms'" in sql
    assert "SET LOCAL row_security = off" in sql
    assert "LIMIT 1025" in sql and "current_user = 'ac_backup'" in sql
    assert "has_table_privilege" in sql and "NOT rolbypassrls" in sql
    assert "public.alembic_version" in sql and sizing.SCHEMA_HEAD in sql
    assert "COMMIT;" not in sql and "INSERT INTO" not in sql
    command = sizing.diagnostic_command(backup, target, sizing.operation_clock() + 60)
    assert '-h 127.0.0.1 -p 5432 -U ac_backup -d "$POSTGRES_DB" -qAt -f -' in command[-1]
    assert 'timeout --signal=KILL "${duration}s"' in command[-1]
    assert "-v cap=55" in command[-1] and "/proc/uptime" in command[-1]
    assert "$AC_DB_BACKUP_PASSWORD" in command[-1]
    assert sql not in " ".join(command)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "identity",
        "negative",
        "bool",
        "float",
        "missing",
        "duplicate",
        "wrong_relation",
        "wrong_version",
        "read_write",
        "timestamp",
        "total",
    ],
)
def test_unsafe_results_are_refused_without_echoing_values(mutation):
    rows = output()
    if mutation == "extra":
        rows[1]["unexpected"] = "fictional-private-value"
    if mutation == "identity":
        rows[1]["relation"] = "fictional-private-value"
    if mutation == "negative":
        rows[1]["parity_count"] = -1
    if mutation == "bool":
        rows[1]["parity_count"] = True
    if mutation == "float":
        rows[1]["parity_count"] = 1.5
    if mutation == "missing":
        rows.pop(1)
    if mutation == "duplicate":
        rows[2] = rows[1]
    if mutation == "wrong_relation":
        rows[1]["relation"] = "unknown"
    if mutation == "wrong_version":
        rows[0]["postgres_version_num"] = 180005
    if mutation == "read_write":
        rows[0]["read_only"] = False
    if mutation == "timestamp":
        rows[-1]["finished_at"] = "2026-10-13T00:01:01.000000Z"
    if mutation == "total":
        rows[1]["total_bytes"] = 1
    with pytest.raises(sizing.Refusal) as error:
        sizing.validate_output(encoded(rows), SMALL_TABLES)
    assert str(error.value) == "unsafe_result"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"[]\n",
        b"NaN\n",
        b"\xff\n",
        b"{}\n" * 1027,
        b"x" * (1024 * 1024 + 1),
        b'{"kind":"database","kind":"database"}\n{}\n{}\n{}\n',
    ],
    ids=["empty", "array", "nan", "non_ascii", "excess_records", "excess_bytes", "duplicate"],
)
def test_malformed_excess_and_duplicate_json(data):
    with pytest.raises(sizing.Refusal):
        sizing.validate_output(data, SMALL_TABLES)


def test_valid_receipt_contains_only_allowed_measurements_and_exact_pins():
    measurements = sizing.validate_output(encoded(output()), SMALL_TABLES)
    pins = {
        "source_sha": "a" * 40,
        "script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        "environment": "production",
    }
    payload = json.loads(sizing.receipt(pins, SMALL_TABLES, measurements))
    assert payload["pins"]["app_sha"] == sizing.APP_SHA
    assert payload["pins"]["sql_sha256"] == sizing.sha256(sizing.fixed_sql(SMALL_TABLES))
    assert payload["application_mutations"] == 0
    assert payload["bytes_semantics"] == "contemporaneous-storage-observations"
    assert "dump_bytes" not in payload and "compression_ratio" not in payload
    assert json.loads(sizing.receipt(pins, SMALL_TABLES, None))["measurements"] is None


def test_duplicate_fields_and_unbounded_integer_are_rejected():
    data = encoded(output()).replace(
        b'"kind": "database"', b'"kind": "database", "kind": "database"'
    )
    with pytest.raises(sizing.Refusal, match="unsafe_result"):
        sizing.validate_output(data, SMALL_TABLES)
    rows = output()
    rows[1]["parity_count"] = 2**63
    with pytest.raises(sizing.Refusal, match="unsafe_result"):
        sizing.validate_output(encoded(rows), SMALL_TABLES)


def test_process_stderr_is_redacted_and_output_is_bounded(monkeypatch):
    for code, reason in [
        ("import sys;sys.stderr.write('fictional-private-value')", "database_refused"),
        ("import sys;sys.stdout.write('x'*2048)", "output_limit"),
    ]:
        monkeypatch.setattr(sizing, "MAX_OUTPUT_BYTES", 1024)
        with pytest.raises(sizing.Refusal, match=reason) as error:
            sizing.bounded_process(
                [sys.executable, "-c", code], b"", {}, sizing.operation_clock() + 3
            )
        assert "fictional-private-value" not in str(error.value)


def test_timeout_kills_descendant_even_after_leader_exit(tmp_path):
    marker = tmp_path / "descendant"
    code = """import os,time,sys
child=os.fork()
if child == 0:
 open(sys.argv[1],'w').write(str(os.getpid()))
 time.sleep(30)
else:
 os._exit(0)
"""
    started = sizing.operation_clock()
    with pytest.raises(sizing.Refusal, match="total_timeout"):
        sizing.bounded_process([sys.executable, "-c", code, str(marker)], b"", {}, started + 2)
    assert sizing.operation_clock() - started < 3
    child = int(marker.read_text())
    # Wait for the kernel exit event; a killed child can briefly remain runnable.
    try:
        descriptor = os.pidfd_open(child)
    except ProcessLookupError:
        return
    try:
        assert select.select([descriptor], [], [], 1)[0]
    finally:
        os.close(descriptor)
    assert sizing.operation_clock() - started < 3


def test_main_default_dry_run_never_connects(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--source-sha",
            "a" * 40,
            "--script-sha256",
            sizing.sha256(SCRIPT.read_bytes()),
        ],
    )
    monkeypatch.setattr(sizing, "load_backup", lambda: SimpleNamespace())
    monkeypatch.setattr(sizing, "inventory", lambda _: SMALL_TABLES)
    monkeypatch.setattr(sizing, "admit", lambda *_: SimpleNamespace())
    monkeypatch.setattr(sizing, "bounded_process", lambda *_: pytest.fail("dry run connected"))
    assert sizing.main() == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry_run"


def test_main_errors_and_signals_are_fixed_safe_codes(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--source-sha",
            "a" * 40,
            "--script-sha256",
            sizing.sha256(SCRIPT.read_bytes()),
        ],
    )

    def fail():
        raise ValueError("fictional-private-value")

    monkeypatch.setattr(sizing, "load_backup", fail)
    assert sizing.main() == 3
    assert capsys.readouterr().err == "postgres-sizing: REFUSED (admission_or_runtime)\n"
    with pytest.raises(sizing.Refusal, match="cancelled"), sizing.operation_limit():
        os.kill(os.getpid(), signal.SIGTERM)


def wait_for_exit(pids, deadline):
    descriptors = []
    try:
        for pid in pids:
            with contextlib.suppress(ProcessLookupError):
                descriptors.append(os.pidfd_open(pid))
        while descriptors:
            remaining = deadline - sizing.operation_clock()
            assert remaining > 0, "owned process outlived operation deadline"
            ready = select.select(descriptors, [], [], remaining)[0]
            assert ready, "owned process outlived operation deadline"
            for fd in ready:
                descriptors.remove(fd)
                os.close(fd)
    finally:
        for fd in descriptors:
            os.close(fd)


@pytest.mark.parametrize("cancel", [False, True], ids=["delayed_start", "client_cancel"])
def test_detached_remote_group_exits_within_shared_deadline(
    tmp_path, monkeypatch, cancel, record_property
):
    monkeypatch.setattr(sizing, "TOTAL_SECONDS", 4)  # scaled smaller, never enlarge limits
    ready_path = tmp_path / "ready"
    os.mkfifo(ready_path)
    ready = os.open(ready_path, os.O_RDWR | os.O_NONBLOCK)
    marker, remote_pid = tmp_path / "reader_pids", tmp_path / "remote_pid"
    reader = """import os,sys,time
child=os.fork()
if child == 0: time.sleep(20)
else:
 open(sys.argv[1],'w').write(str(os.getpid())+','+str(child))
 with open(sys.argv[2],'wb',buffering=0) as ready: ready.write(b'1')
 time.sleep(20)
"""
    thread = None
    started = sizing.operation_clock()
    try:
        with sizing.operation_limit() as deadline:
            time.sleep(0.15)  # admission time consumes the SAME original budget
            command = shlex.join([sys.executable, "-c", reader, str(marker), str(ready_path)])
            guard = sizing.remote_guard(deadline, command)
            bridge = """import subprocess,sys,time
time.sleep(float(sys.argv[1]))
remote=subprocess.Popen([sys.argv[2],'-euc',sys.argv[3]],stdin=sys.stdin,
 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
open(sys.argv[4],'w').write(str(remote.pid))
time.sleep(20)
"""
            if cancel:

                def cancel_client():
                    if select.select([ready], [], [], 3)[0]:
                        os.read(ready, 1)
                        os.kill(os.getpid(), signal.SIGTERM)

                thread = threading.Thread(target=cancel_client)
                thread.start()
            with pytest.raises(sizing.Refusal, match="cancelled" if cancel else "total_timeout"):
                sizing.bounded_process(
                    [
                        sys.executable,
                        "-c",
                        bridge,
                        "0.7" if cancel else "1.7",
                        shutil.which("sh"),
                        guard,
                        str(remote_pid),
                    ],
                    b"",
                    {},
                    deadline,
                )
        if thread is not None:
            thread.join(timeout=1)
            assert not thread.is_alive()
        pids = [int(remote_pid.read_text()), *map(int, marker.read_text().split(","))]
        wait_for_exit(pids, deadline)
        assert sizing.operation_clock() - started < 4
        record_property("operation_bound_seconds", 4)
        record_property("all_owned_processes_exited_seconds", sizing.operation_clock() - started)
    finally:
        os.close(ready)
        for path in (remote_pid, marker):
            if path.exists():
                for pid in map(int, path.read_text().split(",")):
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)


def test_remote_refuses_expired_start_without_launching_reader(tmp_path):
    marker = tmp_path / "launched"
    command = shlex.join(
        [sys.executable, "-c", "import sys;open(sys.argv[1],'w').close()", str(marker)]
    )
    guard = sizing.remote_guard(sizing.operation_clock() - 1, command)
    result = subprocess.run(  # noqa: S603 - fixed fictional guard and reader
        [shutil.which("sh"), "-euc", guard],
        capture_output=True,
        timeout=2,
        check=False,
    )
    assert result.returncode == 3 and not marker.exists()


def test_remote_guard_preserves_reader_stdin():
    guard = sizing.remote_guard(sizing.operation_clock() + 3, shutil.which("cat"))
    result = subprocess.run(  # noqa: S603 - fictional stdin through exact guard
        [shutil.which("sh"), "-euc", guard],
        input=b"fictional-sql-input\n",
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 0 and result.stdout == b"fictional-sql-input\n"
    assert not result.stderr


def test_remote_refuses_a_different_clock_namespace(monkeypatch):
    monkeypatch.setattr(sizing.os, "readlink", lambda _: "time:[0]")
    guard = sizing.remote_guard(sizing.operation_clock() + 3, "echo unsafe")
    result = subprocess.run(  # noqa: S603 - mismatch must refuse before command
        [shutil.which("sh"), "-euc", guard],
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 3 and not result.stdout


@pytest.mark.parametrize("provide_path", [False, True], ids=["missing_path", "explicit_path"])
def test_read_launch_under_audited_wrapper_environment(tmp_path, provide_path):
    run_id = "11111111-1111-4111-8111-111111111111"
    directory = tmp_path / f"paperclip-run-fictional-{run_id[:12]}-candidate"
    directory.mkdir(mode=0o700)
    script = directory / "ac-postgres-sizing.py"
    script.write_bytes(SCRIPT.read_bytes())
    wrapper = directory / "fictional_wrapper.py"
    wrapper.write_text("""import importlib.util,sys,types
spec=importlib.util.spec_from_file_location('sizing',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
fake=types.SimpleNamespace(compose_environment=lambda _: {})
program="import sys;sys.stdout.buffer.write("+sys.argv[2]+")"
fake.compose_command=lambda *args: [sys.executable,'-c',program]
m.load_backup=lambda:fake
m.inventory=lambda _:('alembic_version','fictional_records')
m.admit=lambda *args:fake
sys.argv=[sys.argv[1]]+sys.argv[3:]
sys.exit(m.main())
""")
    # Matches ac-root's read-back child whitelist; no scratch variables or secrets.
    environment = {
        "PATH": os.defpath,
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "PAPERCLIP_RUN_ID": run_id,
        "AC_ROOT_TASK": "fictional-source-task",
    }
    args = [
        sys.executable,
        str(wrapper),
        str(script),
        repr(encoded(output())),
        "--source-sha",
        "a" * 40,
        "--script-sha256",
        sizing.sha256(script.read_bytes()),
        "--read",
    ]
    if provide_path:
        args += ["--scratch-dir", str(directory)]
    result = subprocess.run(args, env=environment, capture_output=True, timeout=3, check=False)  # noqa: S603
    if provide_path:
        assert result.returncode == 0 and json.loads(result.stdout)["mode"] == "read"
        assert not result.stderr
    else:
        assert result.returncode == 3 and b"scratch_unavailable" in result.stderr


def test_scratch_rejects_symlink_writable_and_foreign_run(tmp_path, monkeypatch):
    run = "11111111-1111-4111-8111-111111111111"
    directory = tmp_path / run
    directory.mkdir(mode=0o700)
    script = directory / "sizing.py"
    script.write_bytes(SCRIPT.read_bytes())
    monkeypatch.setenv("PAPERCLIP_RUN_ID", run)
    monkeypatch.setattr(sizing, "__file__", str(script))
    assert sizing.validate_scratch(directory) == directory
    link = tmp_path / "link"
    link.symlink_to(directory)
    with pytest.raises(sizing.Refusal, match="scratch_unsafe"):
        sizing.validate_scratch(link)
    directory.chmod(0o777)
    with pytest.raises(sizing.Refusal, match="scratch_unsafe"):
        sizing.validate_scratch(directory)
    directory.chmod(0o700)
    monkeypatch.setenv("PAPERCLIP_RUN_ID", "22222222-2222-4222-8222-222222222222")
    with pytest.raises(sizing.Refusal, match="scratch_unsafe"):
        sizing.validate_scratch(directory)
