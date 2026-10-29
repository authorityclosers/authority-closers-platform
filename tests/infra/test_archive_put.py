"""Archive helper proofs use only loopback Infisical and a fake AWS executable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

HELPER = Path(__file__).resolve().parents[2] / "infra/application/scripts/ac-archive-put"
VALUES = {
    "AC_ARCHIVE_AWS_ACCESS_KEY_ID": "FAKE-ARCHIVE-ACCESS",
    "AC_ARCHIVE_AWS_SECRET_ACCESS_KEY": "FAKE-ARCHIVE-SECRET",
    "AC_ARCHIVE_BUCKET": "fake-archive-bucket",
    "AC_ARCHIVE_REGION": "ap-southeast-2",
}
TOKEN = "fake-token-that-must-never-appear-in-argv"  # noqa: S105 - loopback fixture
CLIENT_ID = "fake-vps-client"
CLIENT_SECRET = "fake-vps-client-secret"  # noqa: S105 - loopback fixture

FAKE_AWS = r"""
import json, os, pathlib, sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
with (root / "aws-argv").open("a") as log:
    log.write(json.dumps(args) + "\n")
assert os.environ["AWS_ACCESS_KEY_ID"] == "FAKE-ARCHIVE-ACCESS"
assert os.environ["AWS_SECRET_ACCESS_KEY"] == "FAKE-ARCHIVE-SECRET"
assert os.environ["AWS_DEFAULT_REGION"] == "ap-southeast-2"
assert os.environ["AWS_CONFIG_FILE"] == "/dev/null"
assert os.environ["AWS_SHARED_CREDENTIALS_FILE"] == "/dev/null"
assert not any("INFISICAL" in name for name in os.environ)
assert "AWS_ENDPOINT_URL" not in os.environ
mode = (root / "mode").read_text() if (root / "mode").exists() else ""
if mode in {"upload-fail", "head-fail"}:
    if mode == "upload-fail" or args[0] == "s3api":
        print("FAKE-ARCHIVE-SECRET fake-token-that-must-never-appear-in-argv", file=sys.stderr)
        sys.exit(1)
objects_path = root / "objects.json"
if args[:2] == ["s3", "cp"]:
    assert args[args.index("--storage-class") + 1] == "GLACIER_IR"
    source = pathlib.Path(args[2])
    prefix = args[3].removeprefix("s3://fake-archive-bucket/")
    if source.is_dir():
        assert "--recursive" in args and "--no-follow-symlinks" in args
        objects = {prefix + f.relative_to(source).as_posix(): f.stat().st_size
                   for f in source.rglob("*") if f.is_file()}
    else:
        assert "--recursive" not in args
        objects = {prefix: source.stat().st_size}
    if mode == "partial":
        objects.pop(next(iter(objects)))
    objects_path.write_text(json.dumps(objects))
    if mode == "changed":
        target = next(iter(source.rglob("*"))) if source.is_dir() else source
        target.write_text("changed")
    if mode == "added":
        (source / "new-file").write_text("new")
    print("FAKE-ARCHIVE-SECRET")
elif args[:2] == ["s3api", "head-object"]:
    assert args[args.index("--bucket") + 1] == "fake-archive-bucket"
    key = args[args.index("--key") + 1]
    objects = json.loads(objects_path.read_text())
    if key not in objects:
        sys.exit(1)
    print(json.dumps({"ContentLength": objects[key] + (1 if mode == "wrong-size" else 0)}))
else:
    sys.exit(2)
"""


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    requests = []

    class Infisical(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def reply(self, payload: object, status: int = 200) -> None:
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_POST(self) -> None:
            assert self.path == "/api/v1/auth/universal-auth/login"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body == {"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET}
            requests.append("login")
            if (tmp_path / "login-fail").exists():
                self.reply({"error": CLIENT_SECRET}, 403)
            else:
                self.reply({"accessToken": TOKEN})

        def do_GET(self) -> None:
            assert self.headers["Authorization"] == f"Bearer {TOKEN}"
            parsed = urlsplit(self.path)
            assert parse_qs(parsed.query) == {
                "projectId": ["test-project"],
                "environment": ["prod"],
                "secretPath": ["/ops"],
            }
            name = parsed.path.removeprefix("/api/v4/secrets/")
            assert name in VALUES
            requests.append(name)
            if (tmp_path / "secret-fail").exists():
                self.reply({"error": TOKEN}, 403)
            else:
                self.reply({"secret": {"secretValue": VALUES[name]}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Infisical)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bootstrap = tmp_path / "bootstrap.env"
    bootstrap.write_text(
        f"export INFISICAL_VPS_CLIENT_ID='{CLIENT_ID}'\n"
        f"INFISICAL_VPS_CLIENT_SECRET='{CLIENT_SECRET}'\n"
        "INFISICAL_PROJECT_ID=test-project\n"
    )
    aws = tmp_path / "aws"
    aws.write_text(f"#!{sys.executable}\n{FAKE_AWS}")
    aws.chmod(0o755)
    monkeypatch.setenv("AC_ARCHIVE_BOOTSTRAP", str(bootstrap))
    monkeypatch.setenv("AC_ARCHIVE_API_URL", f"http://127.0.0.1:{server.server_port}/api")
    monkeypatch.setenv("AC_ARCHIVE_AWS", str(aws))
    # These must not affect the isolated AWS environment.
    monkeypatch.setenv("INFISICAL_TOKEN", TOKEN)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://invalid-inherited-endpoint")
    try:
        yield tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert all(name in {"login", *VALUES} for name in requests)


def run(path: Path, key: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - local helper with fake endpoint/executable
        [sys.executable, "-I", str(HELPER), str(path), key],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def calls(root: Path) -> list[list[str]]:
    path = root / "aws-argv"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def assert_private(root: Path, result: subprocess.CompletedProcess[str]) -> None:
    observed = result.stdout + result.stderr + json.dumps(calls(root))
    for value in [
        VALUES["AC_ARCHIVE_AWS_ACCESS_KEY_ID"],
        VALUES["AC_ARCHIVE_AWS_SECRET_ACCESS_KEY"],
        TOKEN,
        CLIENT_ID,
        CLIENT_SECRET,
    ]:
        assert value not in observed


def test_single_file_upload_and_size_verification(archive: Path) -> None:
    path = archive / "paperclip-a.sql.gz"
    path.write_bytes(b"not a real backup")
    key = f"backups/paperclip/{path.name}"
    result = run(path, key)
    assert result.returncode == 0, result.stderr
    assert f'key="{key}" size_bytes={path.stat().st_size}' in result.stdout
    assert [c[:2] for c in calls(archive)] == [["s3", "cp"], ["s3api", "head-object"]]
    assert_private(archive, result)


def test_directory_checks_every_object_including_nested_and_zero_length(archive: Path) -> None:
    path = archive / "snapshot with spaces"
    (path / "nested").mkdir(parents=True)
    (path / "backup.dump").write_bytes(b"fake dump")
    (path / "nested" / "metadata.json").write_bytes(b"")
    result = run(path, f"backups/snapshots/{path.name}")
    assert result.returncode == 0, result.stderr
    heads = [c[c.index("--key") + 1] for c in calls(archive) if c[0] == "s3api"]
    assert set(heads) == {
        f"backups/snapshots/{path.name}/backup.dump",
        f"backups/snapshots/{path.name}/nested/metadata.json",
    }
    assert "size_bytes=9" in result.stdout
    assert_private(archive, result)


@pytest.mark.parametrize(
    "mode", ["upload-fail", "head-fail", "wrong-size", "partial", "changed", "added"]
)
def test_failure_never_reports_verified_or_removes_local_files(archive: Path, mode: str) -> None:
    path = archive / "snapshot"
    path.mkdir()
    (path / "backup.dump").write_bytes(b"fake dump")
    (path / "metadata.json").write_bytes(b"{}")
    (archive / "mode").write_text(mode)
    result = run(path, f"backups/snapshots/{path.name}")
    assert result.returncode == 1
    assert not result.stdout
    assert path.exists() and (path / "backup.dump").exists()
    assert_private(archive, result)


@pytest.mark.parametrize("failure", ["login-fail", "secret-fail"])
def test_infisical_failure_does_not_call_aws_or_expose_response(
    archive: Path, failure: str
) -> None:
    path = archive / "old.dump"
    path.write_bytes(b"fake")
    (archive / failure).touch()
    result = run(path, "backups/staging/old.dump")
    assert result.returncode == 1
    assert not calls(archive)
    assert_private(archive, result)


@pytest.mark.parametrize("kind", ["symlink", "nested-symlink", "fifo", "empty"])
def test_unsafe_or_empty_backup_is_refused_before_credentials(archive: Path, kind: str) -> None:
    path = archive / "snapshot"
    path.mkdir()
    if kind == "symlink":
        path.rmdir()
        path.symlink_to(archive, target_is_directory=True)
    elif kind == "nested-symlink":
        (path / "secret-link").symlink_to(archive / "bootstrap.env")
    elif kind == "fifo":
        os.mkfifo(path / "pipe")
    result = run(path, "backups/snapshots/snapshot")
    assert result.returncode == 1
    assert not calls(archive)
    assert_private(archive, result)


@pytest.mark.parametrize(
    "key", ["backups/production/old.dump", "backups/staging/../old.dump", "tests/old.dump"]
)
def test_unapproved_keys_are_refused(archive: Path, key: str) -> None:
    path = archive / "old.dump"
    path.touch()
    result = run(path, key)
    assert result.returncode == 1
    assert not calls(archive)


def test_usage_and_isolated_shebang() -> None:
    result = subprocess.run(  # noqa: S603 - usage only, never fetches credentials
        [sys.executable, "-I", str(HELPER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert HELPER.read_text().startswith("#!/usr/bin/python3 -I\n")
