#!/usr/bin/env python3
"""Rotate the staging Sales Xray runtime database credential.

This is a source-owned operator action.  It is deliberately staging-only and
does not accept a URL, password, destination, or SQL fragment on argv.  The
Infisical machine token, current values, generated password, and database
command bodies stay in process memory or short-lived child stdin/environment.
The command changes only the ``ac_runtime`` password, the two staging
Infisical secrets that contain it, and the existing hosted worker credential
file.  Compose restart and candidate health proof remain separate operator
steps.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows development host
    fcntl = None  # type: ignore[assignment]

STAGING_ENVIRONMENT = "staging"
PRODUCTION_ENVIRONMENT = "prod"
INFISICAL_PROJECT_ID = "b421c44e-4599-4394-8df6-758ed8aedfed"
INFISICAL_PATH = "/application"
INFISICAL_API_DEFAULT = "https://app.infisical.com/api"
DOCKER_EXECUTABLE = "/usr/bin/docker"
DATABASE_HOST = "postgres"
DATABASE_NAME = "ac_platform"
RUNTIME_ROLE = "ac_runtime"
MIGRATOR_ROLE = "ac_migrator"
OWNER_ROLE = "ac_owner"
WORKER_UID = 10001
ROOT_UID = 0
ROOT_GID = 0
DATABASE_FILE = Path("/etc/authority-closers/secrets/sales-xray/staging/database-url")
DATABASE_FILE_MODE = 0o400
MAX_DATABASE_URL_BYTES = 4096


class RotationError(Exception):
    """A content-free operator failure with non-secret reconciliation status."""

    def __init__(self, message: str, *, rollback: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.rollback = rollback


@dataclass(frozen=True)
class DatabaseProfile:
    username: str
    password: str
    host: str = DATABASE_HOST
    port: int = 5432
    database: str = DATABASE_NAME
    sslmode: str | None = None


class SecretStore(Protocol):
    def get(self, key: str, environment: str) -> str: ...

    def set(self, key: str, value: str, environment: str) -> None: ...


class DatabaseClient(Protocol):
    def verify_runtime(self, profile: DatabaseProfile) -> None: ...

    def privilege_snapshot(self, profile: DatabaseProfile) -> dict[str, Any]: ...

    def alter_runtime_password(self, owner: DatabaseProfile, password: str) -> None: ...


def _refuse() -> RotationError:
    return RotationError("Sales Xray database credential rotation refused.")


def _validate_password(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) < 16
        or value != value.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        or value.startswith("local-")
    ):
        raise _refuse()
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        raise _refuse() from None
    return value


def parse_database_url(value: str, expected_user: str) -> DatabaseProfile:
    """Parse only the private Compose URL shape, without exposing its value."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise _refuse()
    try:
        parsed = urlsplit(value)
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        username = parsed.username
        password = parsed.password
        host = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError):
        raise _refuse() from None
    if (
        parsed.scheme != "postgresql+psycopg"
        or parsed.fragment
        or parsed.path != f"/{DATABASE_NAME}"
        or username != expected_user
        or password is None
        or host != DATABASE_HOST
        or port not in (None, 5432)
        or len(query) > 1
        or any(key != "sslmode" or not value for key, value in query)
    ):
        raise _refuse()
    decoded = unquote(password)
    _validate_password(decoded)
    return DatabaseProfile(
        username=expected_user,
        password=decoded,
        host=host,
        port=port or 5432,
        database=DATABASE_NAME,
        sslmode=query[0][1] if query else None,
    )


def render_database_url(profile: DatabaseProfile, password: str) -> str:
    """Render a URL from fixed validated components; never print the result."""

    _validate_password(password)
    netloc = f"{quote(profile.username, safe='')}:{quote(password, safe='')}@{profile.host}"
    if profile.port != 5432:
        netloc += f":{profile.port}"
    query = urlencode({"sslmode": profile.sslmode}) if profile.sslmode else ""
    return urlunsplit(("postgresql+psycopg", netloc, f"/{DATABASE_NAME}", query, ""))


def _owner_profile(password: str) -> DatabaseProfile:
    return DatabaseProfile(username=OWNER_ROLE, password=_validate_password(password))


def _new_password() -> str:
    # urlsafe characters avoid SQL quoting and URL escaping hazards.  The
    # value is never written to a file or included in a command argument.
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _scram_verifier(password: str) -> str:
    """Build a PostgreSQL SCRAM verifier without putting the cleartext in SQL."""

    _validate_password(password)
    iterations = 4096
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    return f"SCRAM-SHA-256${iterations}:{encode(salt)}${encode(stored_key)}:{encode(server_key)}"


def _check_private_parent(path: Path, *, require_owner: bool) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise _refuse()
    cursor = path.parent
    while True:
        try:
            info = cursor.lstat()
        except OSError:
            raise _refuse() from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise _refuse()
        if require_owner and (
            info.st_uid != ROOT_UID or info.st_gid != ROOT_GID or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise _refuse()
        if cursor.parent == cursor:
            return
        cursor = cursor.parent


@contextmanager
def _rotation_lock() -> Any:
    """Serialize rotations without exposing any secret in a lock name."""

    if os.name != "posix" or fcntl is None:
        yield
        return
    lock_parent = Path("/run/lock/authority-closers")
    lock_path = lock_parent / "sales-xray-staging-db-rotation.lock"
    _check_private_parent(lock_parent / "placeholder", require_owner=True)
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError:
        raise _refuse() from None
    try:
        info = os.fstat(descriptor)
        if (
            info.st_uid != ROOT_UID
            or info.st_gid != ROOT_GID
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise _refuse()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise _refuse() from None
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _private_file_read(path: Path, *, require_owner: bool) -> bytes:
    _check_private_parent(path, require_owner=require_owner)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError):
        raise _refuse() from None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size <= 0
            or info.st_size > MAX_DATABASE_URL_BYTES
            or (require_owner and (info.st_uid != WORKER_UID or info.st_gid != ROOT_GID))
            or (require_owner and stat.S_IMODE(info.st_mode) != DATABASE_FILE_MODE)
        ):
            raise _refuse()
        value = os.read(descriptor, MAX_DATABASE_URL_BYTES + 1)
        if len(value) != info.st_size:
            raise _refuse()
        return value
    except RotationError:
        raise
    except OSError:
        raise _refuse() from None
    finally:
        os.close(descriptor)


def _replace_private_file(
    path: Path, expected: bytes, replacement: bytes, *, require_owner: bool
) -> None:
    if _private_file_read(path, require_owner=require_owner) != expected:
        raise _refuse()
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".database-url.rotate.", dir=path.parent
        )
        temporary = Path(temporary_name)
        if os.name == "posix":
            os.fchmod(descriptor, 0)
        offset = 0
        while offset < len(replacement):
            offset += os.write(descriptor, replacement[offset:])
        os.fsync(descriptor)
        if os.name == "posix":
            if require_owner:
                os.fchown(descriptor, WORKER_UID, ROOT_GID)
            os.fchmod(descriptor, DATABASE_FILE_MODE)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        # The parent is root-owned/non-writable on the canonical host.  The
        # pre-check plus atomic replace prevents partial bytes being observed.
        if _private_file_read(path, require_owner=require_owner) != expected:
            raise _refuse()
        os.replace(temporary, path)
        temporary = None
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        if _private_file_read(path, require_owner=require_owner) != replacement:
            raise _refuse()
    except RotationError:
        raise
    except OSError:
        raise _refuse() from None
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()


class InfisicalStore:
    def __init__(self, token: str, *, api_url: str = INFISICAL_API_DEFAULT) -> None:
        if not token or any(character.isspace() for character in token):
            raise _refuse()
        self.token = token
        self.api_url = api_url.rstrip("/")
        if not self.api_url.endswith("/api"):
            self.api_url += "/api"
        parsed = urlsplit(self.api_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise _refuse()

    def _request(
        self, method: str, key: str, environment: str, value: str | None = None
    ) -> dict[str, Any]:
        if environment not in {STAGING_ENVIRONMENT, PRODUCTION_ENVIRONMENT}:
            raise _refuse()
        params = urlencode(
            {
                "projectId": INFISICAL_PROJECT_ID,
                "environment": environment,
                "secretPath": INFISICAL_PATH,
            }
        )
        endpoint = f"{self.api_url}/v4/secrets/{quote(key, safe='')}?{params}"
        body = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if value is not None:
            body = json.dumps(
                {
                    "projectId": INFISICAL_PROJECT_ID,
                    "environment": environment,
                    "secretValue": value,
                    "secretPath": INFISICAL_PATH,
                    "type": "shared",
                },
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            request = Request(  # noqa: S310 - endpoint was fixed to HTTPS above
                endpoint, data=body, headers=headers, method=method
            )
            with urlopen(request, timeout=20) as response:  # noqa: S310 - endpoint is fixed to HTTPS
                payload = response.read(256 * 1024)
        except (HTTPError, URLError, OSError):
            raise _refuse() from None
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _refuse() from None
        if not isinstance(parsed, dict):
            raise _refuse()
        return parsed

    def get(self, key: str, environment: str) -> str:
        payload = self._request("GET", key, environment)
        try:
            value = payload["secret"]["secretValue"]
        except (KeyError, TypeError):
            raise _refuse() from None
        if not isinstance(value, str):
            raise _refuse()
        return value

    def set(self, key: str, value: str, environment: str) -> None:
        self._request("PATCH", key, environment, value)


class PsqlDatabase:
    def __init__(
        self,
        *,
        release_dir: Path | None = None,
        docker_executable: str = DOCKER_EXECUTABLE,
        timeout_seconds: int = 30,
    ) -> None:
        self.release_dir = release_dir or Path(__file__).resolve().parents[1]
        self.docker_executable = docker_executable
        self.timeout_seconds = timeout_seconds

    def _compose_prefix(self) -> list[str]:
        environment_file = self.release_dir / "environments" / "staging.env"
        image_file = self.release_dir / "release-images.env"
        compose_file = self.release_dir / "compose.yaml"
        if not all(
            path.is_file() and not path.is_symlink()
            for path in (environment_file, image_file, compose_file)
        ):
            raise _refuse()
        return [
            self.docker_executable,
            "compose",
            "--project-name",
            "ac-application-staging",
            "--env-file",
            str(environment_file),
            "--env-file",
            str(image_file),
            "--file",
            str(compose_file),
        ]

    @staticmethod
    def _clean_environment() -> dict[str, str]:
        environment = os.environ.copy()
        for key in tuple(environment):
            if key.startswith("INFISICAL_"):
                environment.pop(key, None)
        return environment

    def _run(self, script: str, *, stdin: str | None = None) -> str:
        command = self._compose_prefix() + ["exec", "-T", "postgres", "sh", "-euc", script]
        try:
            completed = subprocess.run(  # noqa: S603 - executable and arguments are fixed
                command,
                input=None if stdin is None else stdin.encode("utf-8"),
                capture_output=True,
                env=self._clean_environment(),
                timeout=self.timeout_seconds,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise _refuse() from None
        try:
            return completed.stdout.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise _refuse() from None

    def verify_runtime(self, profile: DatabaseProfile) -> None:
        script = (
            "IFS= read -r runtime_password || exit 1; "
            'PGPASSWORD="$runtime_password" psql -h 127.0.0.1 '
            "-U ac_runtime -d ac_platform --no-psqlrc --quiet "
            "--tuples-only --no-align --command "
            "\"SELECT current_user WHERE current_user = 'ac_runtime';\""
        )
        if self._run(script, stdin=profile.password + "\n") != RUNTIME_ROLE:
            raise _refuse()

    def privilege_snapshot(self, profile: DatabaseProfile) -> dict[str, Any]:
        script = (
            "IFS= read -r owner_password || exit 1; "
            'PGPASSWORD="$owner_password" psql -h 127.0.0.1 '
            "-U ac_owner -d ac_platform --no-psqlrc --quiet "
            "--set ON_ERROR_STOP=1 --tuples-only --no-align"
        )
        output = self._run(script, stdin=profile.password + "\n" + _PRIVILEGE_SNAPSHOT_SQL)
        try:
            snapshot = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            raise _refuse() from None
        if not isinstance(snapshot, dict) or snapshot.get("role") != RUNTIME_ROLE:
            raise _refuse()
        return snapshot

    def alter_runtime_password(self, owner: DatabaseProfile, password: str) -> None:
        verifier = _scram_verifier(password).replace("'", "''")
        script = (
            "IFS= read -r owner_password || exit 1; "
            'PGPASSWORD="$owner_password" psql -h 127.0.0.1 '
            "-U ac_owner -d ac_platform --no-psqlrc --quiet "
            "--set ON_ERROR_STOP=1"
        )
        # The cleartext never enters SQL.  The owner password is consumed by
        # the shell's stdin read; only a verifier is sent to PostgreSQL.  The
        # local setting prevents statement logging from recording the ALTER.
        sql = (
            "BEGIN;\n"
            "SET LOCAL log_statement = 'none';\n"
            f"ALTER ROLE ac_runtime PASSWORD '{verifier}';\n"
            "COMMIT;\n"
        )
        self._run(script, stdin=f"{owner.password}\n{sql}")


_PRIVILEGE_SNAPSHOT_SQL = """
WITH role_row AS (
  SELECT oid, rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb,
         rolcanlogin, rolreplication, rolbypassrls, rolconnlimit
    FROM pg_roles WHERE rolname = 'ac_runtime'
), memberships AS (
  SELECT COALESCE(json_agg(parent.rolname ORDER BY parent.rolname), '[]'::json) AS values
    FROM role_row
    LEFT JOIN pg_auth_members membership ON membership.member = role_row.oid
    LEFT JOIN pg_roles parent ON parent.oid = membership.roleid
), table_grants AS (
  SELECT COALESCE(json_agg(json_build_object(
           'schema', table_schema, 'table', table_name, 'privilege', privilege_type
         ) ORDER BY table_schema, table_name, privilege_type), '[]'::json) AS values
    FROM information_schema.role_table_grants
   WHERE grantee = 'ac_runtime'
)
SELECT json_build_object(
  'role', role_row.rolname,
  'rolsuper', role_row.rolsuper,
  'rolinherit', role_row.rolinherit,
  'rolcreaterole', role_row.rolcreaterole,
  'rolcreatedb', role_row.rolcreatedb,
  'rolcanlogin', role_row.rolcanlogin,
  'rolreplication', role_row.rolreplication,
  'rolbypassrls', role_row.rolbypassrls,
  'rolconnlimit', role_row.rolconnlimit,
  'memberships', memberships.values,
  'table_grants', table_grants.values,
  'database_connect', has_database_privilege('ac_runtime', current_database(), 'CONNECT'),
  'database_create', has_database_privilege('ac_runtime', current_database(), 'CREATE'),
  'database_temp', has_database_privilege('ac_runtime', current_database(), 'TEMPORARY'),
  'schema_usage', has_schema_privilege('ac_runtime', 'public', 'USAGE'),
  'schema_create', has_schema_privilege('ac_runtime', 'public', 'CREATE')
)
FROM role_row, memberships, table_grants;
"""


def _rotate_staging_unlocked(
    store: SecretStore,
    database: DatabaseClient,
    *,
    database_file: Path = DATABASE_FILE,
    require_file_owner: bool = True,
    compare_production: bool = True,
) -> dict[str, Any]:
    """Perform the bounded staging rotation with rollback on every failure."""

    old_runtime_password = store.get("AC_DB_RUNTIME_PASSWORD", STAGING_ENVIRONMENT)
    runtime_url = store.get("AC_DATABASE_URL", STAGING_ENVIRONMENT)
    migrator_url = store.get("AC_DATABASE_MIGRATOR_URL", STAGING_ENVIRONMENT)
    owner_password = store.get("AC_POSTGRES_OWNER_PASSWORD", STAGING_ENVIRONMENT)
    runtime = parse_database_url(runtime_url, RUNTIME_ROLE)
    if not hmac.compare_digest(runtime.password, _validate_password(old_runtime_password)):
        raise _refuse()
    parse_database_url(migrator_url, MIGRATOR_ROLE)
    owner = _owner_profile(owner_password)
    if compare_production:
        production_password = store.get("AC_DB_RUNTIME_PASSWORD", PRODUCTION_ENVIRONMENT)
        production_overlap = hmac.compare_digest(old_runtime_password, production_password)
    else:
        production_overlap = None
    old_file = _private_file_read(database_file, require_owner=require_file_owner)
    if old_file != runtime_url.encode("utf-8"):
        raise _refuse()
    database.verify_runtime(runtime)
    before = database.privilege_snapshot(owner)
    new_password = _new_password()
    new_url = render_database_url(runtime, new_password)
    attempted = {"database": False, "file": False, "store": False}
    try:
        attempted["database"] = True
        database.alter_runtime_password(owner, new_password)
        database.verify_runtime(DatabaseProfile(**{**runtime.__dict__, "password": new_password}))
        after = database.privilege_snapshot(owner)
        if after != before:
            raise _refuse()
        attempted["file"] = True
        _replace_private_file(
            database_file,
            old_file,
            new_url.encode("utf-8"),
            require_owner=require_file_owner,
        )
        attempted["store"] = True
        store.set("AC_DB_RUNTIME_PASSWORD", new_password, STAGING_ENVIRONMENT)
        store.set("AC_DATABASE_URL", new_url, STAGING_ENVIRONMENT)
        if store.get("AC_DB_RUNTIME_PASSWORD", STAGING_ENVIRONMENT) != new_password:
            raise _refuse()
        if store.get("AC_DATABASE_URL", STAGING_ENVIRONMENT) != new_url:
            raise _refuse()
    except BaseException:
        # Marking before each call matters: a provider or filesystem write can
        # commit and then fail while returning/readback, leaving no normal
        # return point at which to set a post-write flag.
        rollback = {
            "store": "not-attempted",
            "file": "not-attempted",
            "database": "not-attempted",
        }
        if attempted["store"]:
            try:
                store.set("AC_DATABASE_URL", runtime_url, STAGING_ENVIRONMENT)
                store.set("AC_DB_RUNTIME_PASSWORD", old_runtime_password, STAGING_ENVIRONMENT)
                if (
                    store.get("AC_DATABASE_URL", STAGING_ENVIRONMENT) == runtime_url
                    and store.get("AC_DB_RUNTIME_PASSWORD", STAGING_ENVIRONMENT)
                    == old_runtime_password
                ):
                    rollback["store"] = "verified"
                else:
                    rollback["store"] = "uncertain"
            except Exception:
                rollback["store"] = "uncertain"
        if attempted["file"]:
            try:
                current_file = _private_file_read(database_file, require_owner=require_file_owner)
                if current_file != old_file:
                    if current_file != new_url.encode("utf-8"):
                        rollback["file"] = "uncertain"
                    else:
                        _replace_private_file(
                            database_file,
                            current_file,
                            old_file,
                            require_owner=require_file_owner,
                        )
                if _private_file_read(database_file, require_owner=require_file_owner) == old_file:
                    rollback["file"] = "verified"
                elif rollback["file"] != "uncertain":
                    rollback["file"] = "uncertain"
            except Exception:
                rollback["file"] = "uncertain"
        if attempted["database"]:
            try:
                database.alter_runtime_password(owner, old_runtime_password)
                database.verify_runtime(runtime)
                rollback["database"] = "verified"
            except Exception:
                rollback["database"] = "uncertain"
        raise RotationError(
            "Sales Xray database credential rotation refused.", rollback=rollback
        ) from None
    return {
        "schema": "ac.sales-xray.database-credential-rotation/1",
        "status": "rotated",
        "environment": STAGING_ENVIRONMENT,
        "updated_infisical_keys": ["AC_DB_RUNTIME_PASSWORD", "AC_DATABASE_URL"],
        "worker_credential_file_updated": True,
        "privilege_snapshot_unchanged": True,
        "production_runtime_password_matches_staging_before_rotation": production_overlap,
        "restart_required": True,
        "provider_calls": 0,
        "secret_values_emitted": False,
    }


def rotate_staging(
    store: SecretStore,
    database: DatabaseClient,
    *,
    database_file: Path = DATABASE_FILE,
    require_file_owner: bool = True,
    compare_production: bool = True,
) -> dict[str, Any]:
    with _rotation_lock():
        return _rotate_staging_unlocked(
            store,
            database,
            database_file=database_file,
            require_file_owner=require_file_owner,
            compare_production=compare_production,
        )


def _rollback_summary(rollback: dict[str, str] | None) -> str:
    if rollback is None:
        return "not-started"
    if any(status == "uncertain" for status in rollback.values()):
        return "uncertain"
    if all(status in {"verified", "not-attempted"} for status in rollback.values()):
        return "verified"
    return "uncertain"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-production-compare",
        action="store_true",
        help="Skip the read-only in-memory comparison with the production runtime secret.",
    )
    args = parser.parse_args(argv)
    try:
        if os.name != "posix" or os.geteuid() != ROOT_UID:
            raise _refuse()
        token = os.environ["INFISICAL_TOKEN"]
        store = InfisicalStore(
            token,
            api_url=os.environ.get("INFISICAL_API_URL", INFISICAL_API_DEFAULT),
        )
        database = PsqlDatabase()
        rotate_staging(
            store,
            database,
            compare_production=not args.skip_production_compare,
        )
    except RotationError as error:
        print(
            "FAIL Sales Xray staging database credential rotation refused; "
            f"rollback={_rollback_summary(error.rollback)}.",
            file=sys.stderr,
        )
        return 2
    except (KeyError, OSError, ValueError):
        print(
            "FAIL Sales Xray staging database credential rotation refused; rollback=not-started.",
            file=sys.stderr,
        )
        return 2
    print(
        "PASS Sales Xray staging database credential rotated; restart and candidate "
        "health proof remain required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
