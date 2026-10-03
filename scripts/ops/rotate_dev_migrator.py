#!/usr/bin/env python3
"""Rotate the development ``ac_migrator`` database password (AUT-833, AUT-119).

Root-only operator action under OWNER-APPROVED SECRETS.  It is development
only: the database is the ``acdev-postgres`` container's ``ac_platform``, the
role is ``ac_migrator`` and the only credential file it writes is the
root-only ``/etc/authority-closers/development/migrator.env``.  Staging,
production and the ``ac_runtime`` credential are never read or changed.

No URL, password or SQL fragment is accepted on argv.  The current migrator
URL comes from ``migrator.env``; the bootstrap ``ac_owner`` password stays
inside the container (its own ``POSTGRES_PASSWORD``); the new password is
generated here and reaches PostgreSQL only as a SCRAM verifier on stdin.
Output, receipts and errors carry fixed codes and booleans, never values.

Without ``--apply`` it is a read-only dry-run.  ``--apply`` keeps a root-only
backup of the current ``migrator.env`` before the one-transaction password
change, verifies the new login (and that the old one is refused), replaces
the file atomically and writes a redacted receipt.  A completed receipt makes
a repeated apply a no-op.  ``--rollback RUN_ID --apply`` restores a run's
backup credential in the database and the file.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlsplit, urlunsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows development host
    fcntl = None  # type: ignore[assignment]

ENVIRONMENT = "development"
CONTAINER = "acdev-postgres"
DATABASE = "ac_platform"
ROLE = "ac_migrator"
OWNER_ROLE = "ac_owner"
CONTAINER_PORT = 5432
DOCKER = "/usr/bin/docker"
SCHEMA = "ac.development.migrator-credential-rotation/1"
URL_SCHEMES = ("postgresql+psycopg", "postgresql")
MAX_FILE_BYTES = 64 * 1024
RUN_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z")
ISSUE = re.compile(r"AUT-[0-9]{1,6}\Z")
APPROVER = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:@()-]{1,79}\Z")
APPROVAL_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:#/-]{0,159}\Z")
FINGERPRINT_CONTEXT = b"ac-dev-migrator-rotation/1\0"


class RotationError(Exception):
    """A content-free refusal: ``code`` is a fixed token, never a value."""

    def __init__(self, code: str, *, rollback: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.rollback = rollback


@dataclass(frozen=True)
class Paths:
    development: Path = Path("/etc/authority-closers/development")
    lock: Path = Path("/run/lock/ac-dev-migrator-rotation.lock")
    # Other development consumers of the role.  They are reported, never
    # changed: the agent-readable copies and the frozen API/worker profile
    # must not receive the new credential.
    consumers: tuple[Path, ...] = (
        Path("/home/acdev/.config/acdev/database.env"),
        Path("/home/acdev/.config/acdev/api.env"),
        Path("/etc/authority-closers/secrets/sales-xray/development/api.env"),
    )
    owner_uid: int = 0
    owner_gid: int = 0

    @property
    def migrator_env(self) -> Path:
        return self.development / "migrator.env"

    @property
    def rotation(self) -> Path:
        return self.development / "credential-rotation"


@dataclass(frozen=True)
class Endpoint:
    scheme: str
    host: str
    port: int
    query: str


@dataclass
class Approval:
    issue: str
    approver: str
    reference: str | None = None


@dataclass
class State:
    original: bytes
    lines: list[str]
    endpoint: Endpoint
    password: str = field(repr=False)


class Database(Protocol):
    def endpoints(self) -> tuple[set[str], set[tuple[str, int]]]: ...

    def login(self, host: str, password: str) -> bool: ...

    def snapshot(self) -> dict[str, Any]: ...

    def set_verifier(self, verifier: str) -> None: ...


def refuse(code: str) -> RotationError:
    return RotationError(code)


def now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def new_password() -> str:
    # URL-safe alphabet: no quoting or escaping hazards anywhere downstream.
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def fingerprint(password: str) -> str:
    # Only ever applied to a generated 256-bit password, so the digest cannot
    # be reversed; it lets idempotence recognise the completed rotation.
    return hashlib.sha256(FINGERPRINT_CONTEXT + password.encode("utf-8")).hexdigest()[:24]


def scram_verifier(password: str) -> str:
    """PostgreSQL SCRAM-SHA-256 verifier: the cleartext never enters SQL."""

    salt = secrets.token_bytes(16)
    iterations = 4096
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def b64(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def valid_password(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and len(value) <= 1024
        and not any(ord(c) < 0x20 or ord(c) == 0x7F for c in value)
    )


def parse_url(value: str) -> tuple[Endpoint, str]:
    """Accept only an ``ac_migrator`` URL for ``ac_platform``; never echo it."""

    try:
        parsed = urlsplit(value)
        username, password = parsed.username, parsed.password
        host, port = parsed.hostname, parsed.port
    except (UnicodeError, ValueError):
        raise refuse("migrator_url_invalid") from None
    if (
        parsed.scheme not in URL_SCHEMES
        or parsed.fragment
        or parsed.path != f"/{DATABASE}"
        or username != ROLE
        or password is None
        or not host
        or port is None
    ):
        raise refuse("migrator_url_invalid")
    if parsed.query and not re.fullmatch(r"sslmode=[a-z-]+", parsed.query):
        raise refuse("migrator_url_invalid")
    decoded = unquote(password)
    if not valid_password(decoded):
        raise refuse("migrator_url_invalid")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise refuse("migrator_endpoint_not_ip") from None
    return Endpoint(parsed.scheme, str(address), port, parsed.query), decoded


def render_url(endpoint: Endpoint, password: str) -> str:
    netloc = f"{ROLE}:{quote(password, safe='')}@{endpoint.host}:{endpoint.port}"
    return urlunsplit((endpoint.scheme, netloc, f"/{DATABASE}", endpoint.query, ""))


def env_lines(raw: bytes) -> tuple[list[str], dict[str, str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise refuse("migrator_env_invalid") from None
    lines = text.splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if not separator or key in values:
            raise refuse("migrator_env_invalid")
        values[key] = value.strip().strip("\"'")
    return lines, values


def check_private_dir(path: Path, paths: Paths) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise refuse("private_dir_invalid") from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != paths.owner_uid
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise refuse("private_dir_invalid")


def read_private(path: Path, paths: Paths, code: str) -> bytes:
    check_private_dir(path.parent, paths)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise refuse(code) from None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != paths.owner_uid
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 0 < info.st_size <= MAX_FILE_BYTES
        ):
            raise refuse(code)
        data = os.read(descriptor, MAX_FILE_BYTES + 1)
        if len(data) != info.st_size:
            raise refuse(code)
        return data
    except OSError:
        raise refuse(code) from None
    finally:
        os.close(descriptor)


def write_private(path: Path, data: bytes, paths: Paths, *, replace: bytes | None = None) -> None:
    """Atomically write a root-only 0600 file; ``replace`` guards against drift."""

    check_private_dir(path.parent, paths)
    if replace is not None and read_private(path, paths, "file_drift") != replace:
        raise refuse("file_drift")
    if replace is None and os.path.lexists(path):
        raise refuse("file_exists")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary: Path | None = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        if os.geteuid() == 0:
            os.fchown(descriptor, paths.owner_uid, paths.owner_gid)
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if replace is None:
            os.link(name, path)
            os.unlink(name)
        else:
            os.replace(name, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if read_private(path, paths, "file_readback_failed") != data:
            raise refuse("file_readback_failed")
    except OSError:
        raise refuse("file_write_failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()


@contextlib.contextmanager
def rotation_lock(paths: Paths) -> Iterator[None]:
    if fcntl is None:  # pragma: no cover - Windows development host
        yield
        return
    try:
        descriptor = os.open(
            paths.lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
    except OSError:
        raise refuse("lock_unavailable") from None
    try:
        info = os.fstat(descriptor)
        if info.st_uid != paths.owner_uid or stat.S_IMODE(info.st_mode) != 0o600:
            raise refuse("lock_unavailable")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise refuse("rotation_in_progress") from None
        yield
    finally:
        os.close(descriptor)


class DockerDatabase:
    """psql inside ``acdev-postgres``; every value travels on stdin."""

    def __init__(self, docker: str = DOCKER, timeout: int = 30) -> None:
        self.docker = docker
        self.timeout = timeout

    def _call(self, argv: list[str], stdin: str | None = None) -> tuple[int, str]:
        env = {"PATH": "/usr/bin:/bin", "HOME": "/root", "LC_ALL": "C"}
        try:
            done = subprocess.run(  # noqa: S603 - fixed executable and arguments
                [self.docker, *argv],
                input=None if stdin is None else stdin.encode("utf-8"),
                capture_output=True,
                env=env,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise refuse("docker_unavailable") from None
        # Exit codes 125-127 belong to docker exec itself, not to psql.
        if done.returncode >= 125:
            raise refuse("docker_unavailable")
        return done.returncode, done.stdout.decode("utf-8", "replace").strip()

    def _owner_sql(self, sql: str) -> str:
        script = (
            f'test "${{POSTGRES_USER:-}}" = {OWNER_ROLE} '
            f'&& test "${{POSTGRES_DB:-}}" = {DATABASE} || exit 3; '
            'PGPASSWORD="${POSTGRES_PASSWORD:-}" exec psql -w '
            f"-U {OWNER_ROLE} -d {DATABASE} --no-psqlrc --quiet "
            "-v ON_ERROR_STOP=1 --tuples-only --no-align"
        )
        code, output = self._call(["exec", "-i", CONTAINER, "sh", "-euc", script], sql)
        if code != 0:
            raise refuse("owner_sql_failed")
        return output

    def endpoints(self) -> tuple[set[str], set[tuple[str, int]]]:
        code, output = self._call(["inspect", "--format", "{{json .NetworkSettings}}", CONTAINER])
        if code != 0:
            raise refuse("dev_container_missing")
        try:
            settings = json.loads(output)
            bridge = {
                str(ipaddress.ip_address(network["IPAddress"]))
                for network in (settings.get("Networks") or {}).values()
                if network.get("IPAddress")
            }
            published = {
                (str(ipaddress.ip_address(binding["HostIp"])), int(binding["HostPort"]))
                for binding in ((settings.get("Ports") or {}).get(f"{CONTAINER_PORT}/tcp") or [])
                if binding.get("HostIp")
            }
        except (TypeError, ValueError, KeyError, AttributeError):
            raise refuse("dev_container_missing") from None
        return bridge, published

    def login(self, host: str, password: str) -> bool:
        address = str(ipaddress.ip_address(host))
        script = (
            "IFS= read -r candidate || exit 3; "
            'PGPASSWORD="$candidate" exec psql -w --no-psqlrc --quiet --tuples-only '
            "--no-align --command 'SELECT current_user' "
            f'"host={address} port={CONTAINER_PORT} dbname={DATABASE} user={ROLE} '
            'connect_timeout=5"'
        )
        code, output = self._call(["exec", "-i", CONTAINER, "sh", "-euc", script], password + "\n")
        if code == 0 and output == ROLE:
            return True
        if code == 2:
            return False
        raise refuse("login_probe_failed")

    def snapshot(self) -> dict[str, Any]:
        output = self._owner_sql(SNAPSHOT_SQL)
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            raise refuse("snapshot_failed") from None
        if not isinstance(value, dict) or value.get("database") != DATABASE:
            raise refuse("snapshot_failed")
        return value

    def set_verifier(self, verifier: str) -> None:
        if not re.fullmatch(
            r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+", verifier
        ):
            raise refuse("verifier_invalid")
        # One transaction; statement logging is off for it so the verifier is
        # not written to the server log either.
        alter = "ALTER ROLE ac_migrator PASSWORD '" + verifier + "';\n"
        self._owner_sql(ALTER_TRANSACTION_SQL + alter + "COMMIT;\n")


ALTER_TRANSACTION_SQL = """BEGIN;
SET LOCAL log_statement = 'none';
SET LOCAL log_min_duration_statement = -1;
SET LOCAL log_min_error_statement = 'panic';
DO $$ BEGIN
  IF current_database() <> 'ac_platform' OR (SELECT count(*) FROM pg_roles
     WHERE rolname = 'ac_migrator' AND rolcanlogin AND NOT rolsuper) <> 1 THEN
    RAISE EXCEPTION 'refused';
  END IF;
END $$;
"""

SNAPSHOT_SQL = """
SELECT json_build_object(
  'database', current_database(),
  'role', r.rolname,
  'rolsuper', r.rolsuper, 'rolinherit', r.rolinherit,
  'rolcreaterole', r.rolcreaterole, 'rolcreatedb', r.rolcreatedb,
  'rolcanlogin', r.rolcanlogin, 'rolreplication', r.rolreplication,
  'rolbypassrls', r.rolbypassrls, 'rolconnlimit', r.rolconnlimit,
  'rolvaliduntil', r.rolvaliduntil,
  'memberships', (SELECT COALESCE(json_agg(p.rolname ORDER BY p.rolname), '[]'::json)
                    FROM pg_auth_members m JOIN pg_roles p ON p.oid = m.roleid
                   WHERE m.member = r.oid),
  'owned_relations', (SELECT count(*) FROM pg_class c WHERE c.relowner = r.oid),
  'database_connect', has_database_privilege(r.rolname, current_database(), 'CONNECT'),
  'schema_create', has_schema_privilege(r.rolname, 'public', 'CREATE')
) FROM pg_roles r WHERE r.rolname = 'ac_migrator';
"""


def load_state(paths: Paths, database: Database) -> State:
    raw = read_private(paths.migrator_env, paths, "migrator_env_invalid")
    lines, values = env_lines(raw)
    if values.get("AC_ENVIRONMENT") != ENVIRONMENT:
        raise refuse("development_environment_required")
    endpoint, password = parse_url(values.get("AC_DATABASE_MIGRATOR_URL", ""))
    bridge, published = database.endpoints()
    is_bridge = endpoint.host in bridge and endpoint.port == CONTAINER_PORT
    if not (is_bridge or (endpoint.host, endpoint.port) in published):
        raise refuse("endpoint_not_dev_container")
    return State(raw, lines, endpoint, password)


def probe_host(state: State, database: Database) -> str:
    bridge, _ = database.endpoints()
    if state.endpoint.host in bridge:
        return state.endpoint.host
    if not bridge:
        raise refuse("endpoint_not_dev_container")
    return sorted(bridge)[0]


def check_login_is_authenticated(host: str, database: Database) -> None:
    # A trust rule would accept any password; prove a wrong one is refused
    # before a login check is allowed to count as evidence.
    if database.login(host, new_password()):
        raise refuse("login_not_password_authenticated")


def rewrite(state: State, password: str) -> bytes:
    url = render_url(state.endpoint, password)
    out = [
        f"AC_DATABASE_MIGRATOR_URL={url}"
        if line.strip().partition("=")[0].strip() == "AC_DATABASE_MIGRATOR_URL"
        else line
        for line in state.lines
    ]
    return ("\n".join(out) + "\n").encode("utf-8")


def consumers(paths: Paths, old_password: str) -> list[dict[str, Any]]:
    """Report other dev holders of the role; never change or print them."""

    report: list[dict[str, Any]] = []
    for path in paths.consumers:
        entry: dict[str, Any] = {"path": str(path), "present": False, "changed": False}
        report.append(entry)
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            entry["present"] = None
            continue
        entry["present"] = True
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
            entry["has_migrator_url"] = None
            continue
        try:
            _, values = env_lines(path.read_bytes())
        except (OSError, RotationError):
            entry["has_migrator_url"] = None
            continue
        url = values.get("AC_DATABASE_MIGRATOR_URL")
        entry["has_migrator_url"] = url is not None
        if url is not None:
            try:
                _, held = parse_url(url)
                entry["holds_pre_rotation_credential"] = hmac.compare_digest(held, old_password)
            except RotationError:
                entry["holds_pre_rotation_credential"] = None
    return report


def receipts(paths: Paths) -> list[dict[str, Any]]:
    if not paths.rotation.exists():
        return []
    check_private_dir(paths.rotation, paths)
    found = []
    for path in sorted(paths.rotation.glob("*.receipt.json")):
        try:
            value = json.loads(read_private(path, paths, "receipt_invalid"))
        except json.JSONDecodeError:
            raise refuse("receipt_invalid") from None
        if value.get("schema") != SCHEMA or not RUN_ID.fullmatch(str(value.get("run_id"))):
            raise refuse("receipt_invalid")
        found.append(value)
    return sorted(found, key=lambda item: (item.get("written_at", ""), item["run_id"]))


def latest_rotation(paths: Paths) -> dict[str, Any] | None:
    """Return the newest rotation receipt that has not been rolled back."""

    history = receipts(paths)
    rolled_back = {item.get("rollback_of") for item in history if item["status"] == "rolled_back"}
    open_runs = [
        item
        for item in history
        if item.get("action") == "rotate" and item["run_id"] not in rolled_back
    ]
    return open_runs[-1] if open_runs else None


def write_receipt(paths: Paths, receipt: dict[str, Any], *, first: bool) -> None:
    path = paths.rotation / f"{receipt['run_id']}.receipt.json"
    if receipt.get("action") == "rollback":
        path = paths.rotation / f"{receipt['run_id']}.rollback.receipt.json"
    receipt["written_at"] = now()
    data = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
    replace = None if first else read_private(path, paths, "receipt_invalid")
    write_private(path, data, paths, replace=replace)


def base_receipt(
    run_id: str, action: str, approval: Approval | None, state: State
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "action": action,
        "environment": ENVIRONMENT,
        "container": CONTAINER,
        "database": DATABASE,
        "role": ROLE,
        "endpoint": f"{state.endpoint.host}:{state.endpoint.port}",
        "issue": approval.issue if approval else None,
        "approver": approval.approver if approval else None,
        "approval_reference": approval.reference if approval else None,
        "started_at": now(),
        "secret_values_emitted": False,
        "provider_calls": 0,
        "runtime_staging_production_changed": False,
    }


def rotate(
    paths: Paths, database: Database, *, apply: bool, approval: Approval | None
) -> dict[str, Any]:
    state = load_state(paths, database)
    previous = latest_rotation(paths)
    host = probe_host(state, database)
    if previous is not None:
        if previous.get("status") == "rotated" and hmac.compare_digest(
            previous.get("new_credential_fingerprint", ""), fingerprint(state.password)
        ):
            if not database.login(host, state.password):
                raise refuse("completed_rotation_login_failed")
            return {**previous, "result": "already_rotated", "changed": False}
        raise refuse(f"previous_run_{previous.get('status', 'unknown')}_needs_rollback")
    check_login_is_authenticated(host, database)
    if not database.login(host, state.password):
        raise refuse("current_login_failed")
    before = database.snapshot()
    report = consumers(paths, state.password)
    plan = {
        "schema": SCHEMA,
        "mode": "apply" if apply else "dry-run",
        "environment": ENVIRONMENT,
        "container": CONTAINER,
        "database": DATABASE,
        "role": ROLE,
        "endpoint": f"{state.endpoint.host}:{state.endpoint.port}",
        "current_login_verified": True,
        "wrong_password_refused": True,
        "privilege_snapshot": before,
        "consumers": report,
        "secret_values_emitted": False,
    }
    if not apply:
        return {**plan, "changed": False}
    if approval is None:
        raise refuse("approval_required")
    if not paths.rotation.exists():
        os.mkdir(paths.rotation, 0o700)
        if os.geteuid() == 0:
            os.chown(paths.rotation, paths.owner_uid, paths.owner_gid)
    check_private_dir(paths.rotation, paths)
    run_id = new_run_id()
    password = new_password()
    replacement = rewrite(state, password)
    backup = paths.rotation / f"{run_id}.backup.env"
    write_private(backup, state.original, paths)
    receipt = base_receipt(run_id, "rotate", approval, state)
    receipt.update(
        {
            "status": "prepared",
            "backup": str(backup),
            "backup_verified": True,
            "migrator_env": str(paths.migrator_env),
            "new_credential_fingerprint": fingerprint(password),
            "consumers": report,
        }
    )
    write_receipt(paths, receipt, first=True)
    attempted = {"database": False, "file": False}
    try:
        attempted["database"] = True
        database.set_verifier(scram_verifier(password))
        if not database.login(host, password):
            raise refuse("new_login_failed")
        if database.login(host, state.password):
            raise refuse("old_login_still_accepted")
        if database.snapshot() != before:
            raise refuse("privilege_snapshot_changed")
        attempted["file"] = True
        write_private(paths.migrator_env, replacement, paths, replace=state.original)
    except BaseException as error:
        code = error.code if isinstance(error, RotationError) else "apply_interrupted"
        rollback = restore(paths, database, host, state, attempted, replacement)
        receipt.update({"status": "failed", "failure": code, "rollback": rollback})
        if all(value in {"verified", "not-attempted"} for value in rollback.values()):
            receipt["status"] = "rolled_back"
            receipt["rollback_of"] = run_id
        with contextlib.suppress(RotationError, OSError):
            write_receipt(paths, receipt, first=False)
        raise RotationError(code, rollback=rollback) from None
    receipt.update(
        {
            "status": "rotated",
            "completed_at": now(),
            "new_login_verified": True,
            "old_login_refused": True,
            "privilege_snapshot_unchanged": True,
            "migrator_env_updated": True,
        }
    )
    write_receipt(paths, receipt, first=False)
    return {**receipt, "result": "rotated", "changed": True}


def restore(
    paths: Paths,
    database: Database,
    host: str,
    state: State,
    attempted: dict[str, bool],
    replacement: bytes,
) -> dict[str, str]:
    result = {"file": "not-attempted", "database": "not-attempted"}
    if attempted["file"]:
        try:
            current = read_private(paths.migrator_env, paths, "migrator_env_invalid")
            if current == replacement:
                write_private(paths.migrator_env, state.original, paths, replace=current)
            ok = read_private(paths.migrator_env, paths, "migrator_env_invalid") == state.original
            result["file"] = "verified" if ok else "uncertain"
        except Exception:
            result["file"] = "uncertain"
    if attempted["database"]:
        try:
            database.set_verifier(scram_verifier(state.password))
            result["database"] = "verified" if database.login(host, state.password) else "uncertain"
        except Exception:
            result["database"] = "uncertain"
    return result


def rollback(
    paths: Paths, database: Database, run_id: str, *, apply: bool, approval: Approval | None
) -> dict[str, Any]:
    if not RUN_ID.fullmatch(run_id):
        raise refuse("run_id_invalid")
    history = {item["run_id"]: item for item in receipts(paths) if item.get("action") == "rotate"}
    original = history.get(run_id)
    if original is None:
        raise refuse("run_not_found")
    latest = latest_rotation(paths)
    if latest is None or latest["run_id"] != run_id:
        raise refuse("run_not_latest_open_rotation")
    backup = read_private(paths.rotation / f"{run_id}.backup.env", paths, "backup_invalid")
    lines, values = env_lines(backup)
    if values.get("AC_ENVIRONMENT") != ENVIRONMENT:
        raise refuse("backup_invalid")
    endpoint, old_password = parse_url(values.get("AC_DATABASE_MIGRATOR_URL", ""))
    state = State(backup, lines, endpoint, old_password)
    current = read_private(paths.migrator_env, paths, "migrator_env_invalid")
    if current != backup:
        _, current_values = env_lines(current)
        _, held = parse_url(current_values.get("AC_DATABASE_MIGRATOR_URL", ""))
        if not hmac.compare_digest(
            fingerprint(held), str(original.get("new_credential_fingerprint"))
        ):
            raise refuse("migrator_env_drift")
    host = probe_host(state, database)
    plan = {
        "schema": SCHEMA,
        "mode": "apply" if apply else "dry-run",
        "action": "rollback",
        "rollback_of": run_id,
        "backup_verified": True,
        "migrator_env_matches_run": True,
        "secret_values_emitted": False,
    }
    if not apply:
        return {**plan, "changed": False}
    if approval is None:
        raise refuse("approval_required")
    check_login_is_authenticated(host, database)
    receipt = base_receipt(run_id, "rollback", approval, state)
    receipt["rollback_of"] = run_id
    database.set_verifier(scram_verifier(old_password))
    if not database.login(host, old_password):
        raise refuse("rollback_login_failed")
    if current != backup:
        write_private(paths.migrator_env, backup, paths, replace=current)
    receipt.update({"status": "rolled_back", "completed_at": now(), "old_login_verified": True})
    write_receipt(paths, receipt, first=True)
    return {**receipt, "changed": True}


def main(
    argv: list[str] | None = None,
    *,
    paths: Paths | None = None,
    database: Database | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Change state (default: dry-run).")
    parser.add_argument("--rollback", metavar="RUN_ID", help="Restore a run's backup credential.")
    parser.add_argument("--issue", help="Tracking issue, e.g. AUT-119 (required with --apply).")
    parser.add_argument("--approver", help="Who approved the change (required with --apply).")
    parser.add_argument("--approval-ref", help="Approval comment reference (optional).")
    args = parser.parse_args(argv)
    paths = paths or Paths()
    database = database or DockerDatabase()
    try:
        approval = None
        if args.apply:
            if not (args.issue and ISSUE.fullmatch(args.issue)):
                raise refuse("issue_invalid")
            if not (args.approver and APPROVER.fullmatch(args.approver)):
                raise refuse("approver_invalid")
            if args.approval_ref is not None and not APPROVAL_REF.fullmatch(args.approval_ref):
                raise refuse("approval_ref_invalid")
            approval = Approval(args.issue, args.approver, args.approval_ref)
        if os.geteuid() != paths.owner_uid:
            raise refuse("root_required")
        with rotation_lock(paths):
            if args.rollback:
                result = rollback(
                    paths, database, args.rollback, apply=args.apply, approval=approval
                )
            else:
                result = rotate(paths, database, apply=args.apply, approval=approval)
    except RotationError as error:
        status = ",".join(f"{k}={v}" for k, v in sorted((error.rollback or {}).items()))
        print(
            f"FAIL dev migrator rotation refused: {error.code}"
            + (f"; rollback {status}" if status else ""),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
