from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
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
    module = backup.canonical()
    (path / "metadata.json").write_text(
        json.dumps(
            {
                "artifact_type": "authority-closers-postgresql-logical",
                "environment": "staging",
                "format": "custom",
                "verification": "pg_restore --list",
                "dump_bytes": len(data),
                "dump_sha256": hashlib.sha256(data).hexdigest(),
                "migration_head": "20261019_0097",
                "parity_contract": module.parity_contract_for_head("20261019_0097"),
                "row_counts": {
                    table: 0 for table in module.parity_tables_for_head("20261019_0097")
                },
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

    def transfer(*args, stdout_limit=backup.MAX_CONTROL_BYTES, destination=None):
        calls.append(args)
        if args[0] == "lsf":
            if "--dirs-only" in args:
                return (NAME + "/\n").encode() if objects else b""
            return "\n".join(sorted(k.rsplit("/", 1)[1] for k in objects)).encode()
        if args[0] == "size":
            return json.dumps(
                {"count": len(objects), "bytes": sum(map(len, objects.values()))}
            ).encode()
        if args[0] == "cat":
            data = objects[args[1]]
            if len(data) > stdout_limit:
                raise backup.Refusal("child_stdout_limit")
            destination.write_bytes(data)
            destination.chmod(0o600)
            return b""
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
        assert kwargs["input"] == KEY.encode()
        assert kwargs["stdout_limit"] == backup.MAX_CONTROL_BYTES
        raise backup.ProcessRefusal("child_failed")

    monkeypatch.setattr(backup, "run_process", fake_run)

    @backup.operation
    def invoke():
        backup.checked(["gpg"], input=KEY.encode())

    with pytest.raises(backup.Refusal, match="^child_failed$") as result:
        invoke()
    assert "sensitive" not in str(result.value)


def test_wrapper_requires_explicit_execution_and_uses_only_encrypted_helper():
    wrapper = (ROOT / "scripts/ops/ac-db-snapshot").read_text()
    assert '"$1" == --execute' in wrapper
    assert '"$helper" capture' in wrapper
    assert "rclone" not in wrapper and "pg_dump" not in wrapper
    assert "rm -rf" not in wrapper


@pytest.fixture
def fictional_encryption(monkeypatch):
    def crypt(source, output, secret, home, *, decrypt=False):
        shutil.copyfile(source, output)
        output.chmod(0o600)

    monkeypatch.setattr(backup, "crypt", crypt)


@pytest.mark.parametrize("corruption", [b"{}", b"[]", b"not json", b"null"])
def test_upload_fetches_remote_receipt_and_refuses_corruption(
    snapshot, remote, fictional_encryption, monkeypatch, corruption
):
    transfer = backup.rclone
    objects, calls = remote

    def corrupt(*args, **kwargs):
        result = transfer(*args, **kwargs)
        if args[0] == "copyto" and args[2].endswith(backup.CIPHER_RECEIPT):
            objects[args[2]] = corruption
        return result

    monkeypatch.setattr(backup, "rclone", corrupt)
    with pytest.raises(
        backup.Refusal, match="ciphertext_receipt_mismatch|invalid_ciphertext_receipt"
    ):
        backup.upload(snapshot, "staging")
    assert any(
        call[:2] == ("cat", backup.identity("staging", NAME) + "/" + backup.CIPHER_RECEIPT)
        for call in calls
    )
    assert {p.name for p in snapshot.parent.iterdir()} == {NAME}
    assert (snapshot / "backup.dump").exists()


def test_partial_remote_pair_refuses_and_is_never_overwritten(
    snapshot, remote, fictional_encryption, monkeypatch
):
    transfer = backup.rclone
    objects, _ = remote

    def fail_receipt(*args, **kwargs):
        if args[0] == "copyto" and args[2].endswith(backup.CIPHER_RECEIPT):
            raise backup.Refusal("child_failed")
        return transfer(*args, **kwargs)

    monkeypatch.setattr(backup, "rclone", fail_receipt)
    with pytest.raises(backup.Refusal, match="child_failed"):
        backup.upload(snapshot, "staging")
    assert len(objects) == 1
    previous = dict(objects)
    with pytest.raises(backup.Refusal, match="remote_snapshot_already_exists"):
        backup.upload(snapshot, "staging")
    assert previous == objects
    assert {p.name for p in snapshot.parent.iterdir()} == {NAME}


@pytest.mark.parametrize("oversized", [backup.CIPHER, backup.CIPHER_RECEIPT, "listing"])
def test_actual_transport_stream_refuses_even_when_remote_size_lies(
    tmp_path, monkeypatch, oversized
):
    import sys

    monkeypatch.setenv("AC_POSTGRES_DRIVE_STAGING_PASSPHRASE", KEY)
    monkeypatch.setattr(backup, "MAX_ARCHIVE_BYTES", 1024)
    out = tmp_path / "output"
    out.mkdir(mode=0o700)
    limits = []

    def transport(*args, stdout_limit=backup.MAX_CONTROL_BYTES, destination=None):
        if args[0] == "size":
            return b'{"count":2,"bytes":2}'
        if args[0] == "lsf" and oversized != "listing":
            return (backup.CIPHER + "\n" + backup.CIPHER_RECEIPT).encode()
        if (
            args[0] == "cat"
            and args[1].endswith(backup.CIPHER_RECEIPT)
            and oversized != backup.CIPHER_RECEIPT
        ):
            destination.write_text("{}")
            destination.chmod(0o600)
            return b""
        limits.append(stdout_limit)
        return backup.checked(
            [sys.executable, "-c", 'import os; os.write(1,b"x"*(2*1024*1024))'],
            stdout_limit=stdout_limit,
            destination=destination,
        )

    monkeypatch.setattr(backup, "rclone", transport)
    with pytest.raises(backup.Refusal, match="^child_stdout_limit$"):
        backup.fetch("staging", NAME, out)
    assert limits == [
        {
            "listing": backup.MAX_CONTROL_BYTES,
            backup.CIPHER: 1024,
            backup.CIPHER_RECEIPT: backup.MAX_SIDECAR_BYTES,
        }[oversized]
    ]
    assert not list(out.iterdir())


def test_scratch_reservation_fails_before_remote_or_workspace(snapshot, remote, monkeypatch):
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(backup.Refusal, match="scratch_reservation_required"):
        backup.upload(snapshot, "staging")
    assert remote == ({}, [])
    assert {p.name for p in snapshot.parent.iterdir()} == {NAME}


def test_pipeline_uses_one_deadline_across_transport_stages(
    snapshot, remote, fictional_encryption, monkeypatch
):
    import sys

    monkeypatch.setattr(backup, "OPERATION_SECONDS", 0.2)
    transfer = backup.rclone

    def slow(*args, **kwargs):
        backup.checked([sys.executable, "-c", "import time; time.sleep(.08)"], stdout_limit=0)
        return transfer(*args, **kwargs)

    monkeypatch.setattr(backup, "rclone", slow)
    with pytest.raises(backup.Refusal, match="^operation_deadline_exceeded$"):
        backup.upload(snapshot, "staging")
    assert {p.name for p in snapshot.parent.iterdir()} == {NAME}


def test_legacy_snapshot_can_be_retained_but_never_uploaded_as_v2(snapshot, remote):
    (snapshot / "metadata.json").unlink()
    backup.validate_snapshot(snapshot, "staging", NAME, allow_legacy=True)
    with pytest.raises(backup.Refusal, match="unexpected_snapshot_entries"):
        backup.upload(snapshot, "staging")
    assert remote == ({}, [])


@pytest.mark.parametrize(
    "field", ["dump_sha256", "dump_bytes", "environment", "row_counts", "migration_head"]
)
def test_metadata_must_bind_the_same_dump_and_environment(snapshot, remote, field):
    path = snapshot / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata[field] = {} if field == "row_counts" else "wrong"
    path.write_text(json.dumps(metadata))
    with pytest.raises(backup.Refusal, match="same_snapshot_metadata_required"):
        backup.upload(snapshot, "staging")
    assert remote == ({}, [])


def test_missing_capture_key_has_no_files_or_capture_effect(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "ROOT", tmp_path / "backups")
    monkeypatch.delenv("AC_POSTGRES_DRIVE_STAGING_PASSPHRASE", raising=False)
    monkeypatch.setattr(backup, "canonical", lambda: pytest.fail("capture before key"))
    for _ in range(30):
        with pytest.raises(backup.Refusal, match="dedicated_infisical_secret_required"):
            backup.capture("staging", "fictional")
    assert not (tmp_path / "backups").exists()


def test_repeated_failed_uploads_keep_exactly_24_and_the_newest_verified_pair(
    snapshot, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    module = backup.canonical()
    monkeypatch.setattr(backup, "ROOT", tmp_path / "backups")
    target = SimpleNamespace(migration_head="20261019_0097")
    monkeypatch.setattr(module, "resolve_application_release", lambda env: target)
    monkeypatch.setattr(module, "assert_healthy", lambda *a, **kw: None)

    def capture_pair(target, work, max_bytes, *, capture_io):
        pair = work / "pair"
        pair.mkdir(mode=0o750)
        for filename in ["backup.dump", "metadata.json"]:
            shutil.copyfile(snapshot / filename, pair / filename)
        return (
            pair / "backup.dump",
            pair / "metadata.json",
            json.loads((pair / "metadata.json").read_text()),
        )

    monkeypatch.setattr(module, "capture_dump", capture_pair)

    def failed_upload(*args):
        raise backup.Refusal("child_failed")

    monkeypatch.setattr(backup, "upload", failed_upload)
    for i in range(30):
        with pytest.raises(backup.Refusal, match="child_failed"):
            backup.capture("staging", f"failure-{i:03d}")
        ring = tmp_path / "backups/staging-snapshots"
        snapshots = list(ring.iterdir())
        assert len(snapshots) == min(i + 1, 24)
        assert any(p.name.endswith(f"failure-{i:03d}") for p in snapshots)
        assert all({f.name for f in p.iterdir()} == backup.FILES for p in snapshots)
    foreign = ring / "foreign-file"
    foreign.write_text("preserve")
    with pytest.raises(backup.Refusal, match="unknown_local_ring_entry"):
        backup.capture("staging", "blocked-by-foreign")
    assert foreign.read_text() == "preserve"
    assert len(list(ring.iterdir())) == 25


def test_failed_capture_leaves_no_published_or_temporary_snapshot(snapshot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = backup.canonical()
    monkeypatch.setattr(backup, "ROOT", tmp_path / "backups")
    monkeypatch.setattr(module, "resolve_application_release", lambda env: SimpleNamespace())
    monkeypatch.setattr(module, "assert_healthy", lambda *a, **kw: None)

    def fail_capture(target, work, max_bytes, **kwargs):
        (work / "partial").write_text("fictional partial dump")
        raise module.BackupError("safe message")

    monkeypatch.setattr(module, "capture_dump", fail_capture)
    for _ in range(30):
        with pytest.raises(backup.Refusal, match="canonical_capture_failed"):
            backup.capture("staging", "failure")
    assert not list((tmp_path / "backups/staging-snapshots").iterdir())


def test_canonical_capture_uses_one_exported_snapshot_for_dump_and_counts(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = backup.canonical()
    monkeypatch.setattr(module, "prepare_directory", lambda p: p.mkdir(exist_ok=True))
    monkeypatch.setattr(module.os, "chown", lambda *a, **kw: None)
    monkeypatch.setattr(module, "is_root_owned", lambda p: True)
    # CI runners have no acops group; chown is stubbed, so only the group lookup is faked.
    monkeypatch.setattr(
        module, "grp", SimpleNamespace(getgrnam=lambda name: SimpleNamespace(gr_gid=os.getgid()))
    )
    events = []
    target = SimpleNamespace(
        environment="staging",
        migration_head="20261019_0097",
        release_dir=tmp_path / ("a" * 40),
        profile_file=tmp_path / "staging.env",
        images_file=tmp_path / "images.env",
        compose_project="ac-application-staging",
    )

    class IO:
        def holder(self, target):
            return SimpleNamespace(
                snapshot_id="00000003-0000001B-1",
                assert_alive=lambda: None,
                close=lambda: events.append("closed"),
            )

        def dump(self, target, snapshot_id, path):
            events.append(("dump", snapshot_id))
            path.write_bytes(b"PGDMPfictional")
            return path.stat().st_size

        def verify(self, target, path):
            assert path.read_bytes() == b"PGDMPfictional"

        def read(self, command, **kwargs):
            assert "SET TRANSACTION SNAPSHOT '00000003-0000001B-1'" in command[-1]
            events.append(("counts", "00000003-0000001B-1"))
            lines = ["__migration_head__|" + target.migration_head] + [
                t + "|7" for t in module.parity_tables_for_head(target.migration_head)
            ]
            return SimpleNamespace(stdout="\n".join(lines))

        def remaining(self):
            return 1

    dump, metadata_path, metadata = module.capture_dump(
        target, tmp_path / "captures", 1024, capture_io=IO()
    )
    assert metadata["dump_sha256"] == hashlib.sha256(dump.read_bytes()).hexdigest()
    assert metadata["dump_bytes"] == dump.stat().st_size
    assert set(metadata["row_counts"].values()) == {7}
    assert json.loads(metadata_path.read_text()) == metadata
    assert events == [("dump", "00000003-0000001B-1"), ("counts", "00000003-0000001B-1"), "closed"]


def test_equal_environment_keys_are_refused_before_capture(snapshot, monkeypatch):
    monkeypatch.setenv("AC_POSTGRES_DRIVE_PRODUCTION_PASSPHRASE", KEY)
    with pytest.raises(backup.Refusal, match="independent_environment_secrets_required"):
        backup.capture("staging", "must-not-capture")
