from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "drive_backup_candidate", ROOT / "scripts/ops/drive_postgres_backup.py"
)
assert SPEC and SPEC.loader
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)
NAME = "20261019T080000Z-fictional"
KEY = "FictionalOnly-Key-0123456789-abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    parent = tmp_path / "snapshots"
    parent.mkdir(mode=0o700)
    path = parent / NAME
    path.mkdir(mode=0o700)
    data = b"PGDMP" + b"fictional database bytes\n" * 1000
    (path / "backup.dump").write_bytes(data)
    (path / "backup.dump.sha256").write_text(hashlib.sha256(data).hexdigest() + "  backup.dump\n")
    (path / "alembic.txt").write_text("20261019_0097\n")
    (path / "receipt.json").write_text(
        json.dumps(
            {
                "environment": "staging",
                "at": NAME.split("-")[0],
                "bytes": len(data),
                "alembic": "20261019_0097",
            }
        )
    )
    for item in path.iterdir():
        item.chmod(0o600)
    monkeypatch.setenv("AC_POSTGRES_DRIVE_STAGING_PASSPHRASE", KEY)
    return path


@pytest.fixture
def remote(monkeypatch):
    objects = {}
    calls = []
    prefix = backup.identity("staging", NAME)

    def transfer(*args):
        calls.append(args)
        if args[0] == "lsf":
            if "--dirs-only" in args:
                return (NAME + "/\n").encode() if objects else b""
            return "\n".join(sorted(k.rsplit("/", 1)[1] for k in objects)).encode()
        if args[0] == "size":
            return json.dumps(
                {"count": len(objects), "bytes": sum(map(len, objects.values()))}
            ).encode()
        assert args[0] == "copyto"
        source, target = args[1:3]
        if source.startswith(prefix):
            Path(target).write_bytes(objects[source])
            Path(target).chmod(0o600)
        else:
            objects[target] = Path(source).read_bytes()
        return b""

    monkeypatch.setattr(backup, "rclone", transfer)
    return objects, calls


def test_default_dry_run_does_not_read_secrets_or_touch_transport(monkeypatch, capsys):
    monkeypatch.setattr(backup, "checked", lambda *a, **kw: pytest.fail("dry-run subprocess"))
    assert backup.main(["upload", "--environment", "production", "--snapshot", NAME]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] and result["plaintext_upload"] is False
    assert result["retention_changed"] is False


@pytest.mark.parametrize(
    "name", ["../escape", "/root/secret", NAME + "/child", "x", "20261019T080000Z-$(id)"]
)
def test_rejects_path_and_shell_injection(name):
    with pytest.raises(backup.Refusal, match="invalid_snapshot_identity"):
        backup.identity("staging", name)


def test_missing_or_other_environment_secret_prevents_any_upload(snapshot, remote, monkeypatch):
    monkeypatch.delenv("AC_POSTGRES_DRIVE_STAGING_PASSPHRASE")
    monkeypatch.setenv("AC_POSTGRES_DRIVE_PRODUCTION_PASSPHRASE", KEY)
    with pytest.raises(backup.Refusal, match="dedicated_infisical_secret_required"):
        backup.upload(snapshot, "staging")
    assert remote == ({}, [])


@pytest.mark.skipif(not shutil.which("gpg"), reason="requires installed GnuPG")
def test_real_encryption_round_trip_only_ciphertext_leaves_host(snapshot, remote, tmp_path):
    objects, calls = remote
    result = backup.upload(snapshot, "staging")
    assert result["upload_download_decrypt"] == "passed"
    assert result["database_restore"] == "not_performed"
    assert len(objects) == 2
    assert {k.rsplit("/", 1)[1] for k in objects} == {backup.CIPHER, backup.CIPHER_RECEIPT}
    assert all(b"fictional database bytes" not in v for v in objects.values())
    assert all("backup.dump" not in arg for call in calls for arg in call)
    out = tmp_path / "restored"
    out.mkdir(mode=0o700)
    recovered = backup.fetch("staging", NAME, out)
    assert recovered["decrypt_checksum"] == "passed"
    assert recovered["database_restore"] == "not_performed"
    assert all((snapshot / f).read_bytes() == (out / f).read_bytes() for f in backup.FILES)
    assert {p.name for p in snapshot.parent.iterdir()} == {NAME}
    assert {p.name for p in out.iterdir()} == backup.FILES
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in out.iterdir())


@pytest.mark.skipif(not shutil.which("gpg"), reason="requires installed GnuPG")
def test_wrong_key_does_not_publish_plaintext(snapshot, remote, tmp_path, monkeypatch):
    backup.upload(snapshot, "staging")
    monkeypatch.setenv(
        "AC_POSTGRES_DRIVE_STAGING_PASSPHRASE",
        "Wrong-Fictional-Key-0123456789-abcdefghijklmnopqrstuvwxyz",
    )
    out = tmp_path / "restored"
    out.mkdir(mode=0o700)
    with pytest.raises(backup.Refusal, match="child_failed"):
        backup.fetch("staging", NAME, out)
    assert not list(out.iterdir())


@pytest.mark.skipif(not shutil.which("gpg"), reason="requires installed GnuPG")
def test_tampered_download_rejected_before_decrypt(snapshot, remote, tmp_path):
    backup.upload(snapshot, "staging")
    objects, _ = remote
    key = next(k for k in objects if k.endswith(".gpg"))
    objects[key] = b"tampered" + objects[key][8:]
    out = tmp_path / "restored"
    out.mkdir(mode=0o700)
    with pytest.raises(backup.Refusal, match="ciphertext_receipt_mismatch"):
        backup.fetch("staging", NAME, out)
    assert not list(out.iterdir())


def test_existing_remote_is_never_overwritten(snapshot, remote, monkeypatch):
    # Exercise the refusal without spending time encrypting a new archive.
    def fake_encrypt(src, dst, *args, **kwargs):
        dst.write_bytes(b"ciphertext")
        dst.chmod(0o600)

    monkeypatch.setattr(backup, "crypt", fake_encrypt)
    objects, calls = remote
    objects[backup.identity("staging", NAME) + "/" + backup.CIPHER] = b"existing"
    with pytest.raises(backup.Refusal, match="remote_snapshot_already_exists"):
        backup.upload(snapshot, "staging")
    assert list(objects.values()) == [b"existing"]
    assert not any(call[0] == "copyto" for call in calls)


@pytest.mark.parametrize(
    "change", ["checksum", "symlink", "hardlink", "extra", "environment", "size"]
)
def test_bad_snapshot_never_calls_transport(snapshot, remote, change):
    dump = snapshot / "backup.dump"
    if change == "checksum":
        dump.write_bytes(b"PGDMPcorrupt")
    elif change == "symlink":
        dump.unlink()
        dump.symlink_to("/etc/passwd")
    elif change == "hardlink":
        os.link(dump, snapshot.parent / "foreign-link")
    elif change == "extra":
        (snapshot / "credential.env").write_text("fictional")
    elif change == "environment":
        receipt = json.loads((snapshot / "receipt.json").read_text())
        receipt["environment"] = "production"
        (snapshot / "receipt.json").write_text(json.dumps(receipt))
    else:
        with dump.open("wb") as stream:
            stream.truncate(backup.MAX_DUMP_BYTES + 1)
    with pytest.raises(backup.Refusal):
        backup.upload(snapshot, "staging")
    assert remote == ({}, [])


@pytest.mark.parametrize("kind", ["traversal", "duplicate", "symlink", "oversize"])
def test_unsafe_tar_members_are_rejected_before_writing(tmp_path, kind):
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as tar:
        for name in sorted(backup.FILES):
            item = tarfile.TarInfo(
                name if kind != "traversal" or name != "backup.dump" else "../escape"
            )
            item.size = 1
            if name == "backup.dump" and kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/passwd"
                item.size = 0
            if name == "receipt.json" and kind == "oversize":
                item.size = backup.MAX_SIDECAR_BYTES + 1
            tar.addfile(item, io.BytesIO(b"x" * item.size))
        if kind == "duplicate":
            tar.addfile(tarfile.TarInfo("backup.dump"), io.BytesIO())
    target = tmp_path / "output"
    target.mkdir()
    with pytest.raises(backup.Refusal):
        backup.extract_archive(archive, target)
    assert not list(target.iterdir())
    assert not (tmp_path / "escape").exists()


def test_child_secret_redaction_and_no_secret_argv(monkeypatch):
    monkeypatch.setenv("INFISICAL_TOKEN", "fictional-sensitive-token")
    monkeypatch.setenv("AC_POSTGRES_DRIVE_STAGING_PASSPHRASE", KEY)

    def fake_run(command, **kwargs):
        assert KEY not in repr(command)
        assert "INFISICAL_TOKEN" not in kwargs["env"]
        assert "AC_POSTGRES_DRIVE_STAGING_PASSPHRASE" not in kwargs["env"]
        return subprocess.CompletedProcess(command, 1, b"", b"fictional-sensitive-token")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    with pytest.raises(backup.Refusal, match="^child_failed$") as result:
        backup.checked(["gpg"], input=KEY.encode())
    assert "sensitive" not in str(result.value)


def test_capture_and_retention_are_preserved_in_candidate():
    wrapper = (ROOT / "scripts/ops/ac-db-snapshot").read_text()
    assert 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 6' in wrapper
    assert "tail -n +25" in wrapper
    assert "--min-age 14d" in wrapper
    assert "drive_postgres_backup.py upload" in wrapper
    assert 'rclone --config /root/ac-drive/rclone.conf copy "$dir"' not in wrapper
