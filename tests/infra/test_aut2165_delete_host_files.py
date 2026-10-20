"""Fictional refusal checks for exact-list cleanup; no real host files are removed."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/data-changes/aut2165_delete_host_files.py"
SPEC = importlib.util.spec_from_file_location("aut2165_cleanup", SOURCE)
assert SPEC and SPEC.loader
CLEANUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLEANUP)


def file_pin(path):
    info = path.stat()
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "allocated_bytes": info.st_blocks * 512,
    }


def test_mutated_manifest_and_unknown_groups_refuse(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"groups":{"fictional":{"files":[]}}}')
    with pytest.raises(ValueError, match="digest"):
        CLEANUP.read_manifest(manifest, ["fictional"])
    monkeypatch.setattr(
        CLEANUP, "MANIFEST_SHA256", hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    with pytest.raises(ValueError, match="known, unique"):
        CLEANUP.read_manifest(manifest, ["different"])
    assert CLEANUP.read_manifest(manifest, ["fictional"])[1] == []


def test_changed_file_symlink_and_hardlink_refuse(tmp_path):
    path = tmp_path / "fictional.dump"
    path.write_bytes(b"fictional backup")
    pin = file_pin(path)
    assert CLEANUP.verify_file(pin)
    path.write_bytes(b"different and longer fictional backup")
    with pytest.raises(ValueError, match="metadata changed"):
        CLEANUP.verify_file(pin)
    pin = file_pin(path)
    link = tmp_path / "other.dump"
    link.hardlink_to(path)
    with pytest.raises(ValueError, match="metadata changed"):
        CLEANUP.verify_file(pin)
    link.unlink()
    path.unlink()
    assert not CLEANUP.verify_file(pin)
    path.symlink_to(link)
    with pytest.raises(ValueError, match="symlink"):
        CLEANUP.verify_file(pin)


def test_no_receipt_never_authorizes_apply():
    with pytest.raises(ValueError, match="verified owner approval"):
        CLEANUP.verify_approval(None, ["fictional"])


def test_root_private_receipt_binds_groups_and_snapshot(tmp_path, monkeypatch):
    receipt = tmp_path / "approval.json"
    receipt.write_text(
        json.dumps(
            {
                "issue": "AUT-2165",
                "manifest_sha256": CLEANUP.MANIFEST_SHA256,
                "approved_by_owner": True,
                "groups": ["older-production-preinstall-backups"],
                "approver": "fictional-owner",
                "approval_ref": "fictional-record",
                "source_owner_checks_ref": "fictional-check",
            }
        )
    )
    receipt.chmod(0o600)
    original = Path.lstat

    def root_owned(path):
        if path != receipt:
            return original(path)
        from types import SimpleNamespace

        info = original(path)
        return SimpleNamespace(st_uid=0, st_mode=info.st_mode)

    monkeypatch.setattr(Path, "lstat", root_owned)
    with pytest.raises(ValueError, match="snapshot"):
        CLEANUP.verify_approval(receipt, ["older-production-preinstall-backups"])
    with pytest.raises(ValueError, match="exact selection"):
        CLEANUP.verify_approval(receipt, ["fictional"])


def test_fictional_apply_is_repeatable_and_preserves_audit_history(tmp_path, monkeypatch):
    from types import SimpleNamespace

    selected = tmp_path / "selected.dump"
    selected.write_bytes(b"fictional disposable backup")
    retained = tmp_path / "retained.dump"
    retained.write_bytes(b"fictional retained backup")
    pin = file_pin(selected)
    journal = tmp_path / "audit.jsonl"
    monkeypatch.setattr(CLEANUP, "AUDIT", journal)
    real_fstat = CLEANUP.os.fstat

    def simulated_root_audit(fd):
        info = real_fstat(fd)
        return SimpleNamespace(st_uid=0, st_nlink=info.st_nlink, st_mode=info.st_mode)

    monkeypatch.setattr(CLEANUP.os, "fstat", simulated_root_audit)
    receipt = {"approver": "fictional-owner", "approval_ref": "fictional-record"}
    result = CLEANUP.execute([pin], receipt, ["fictional"])
    assert result["removed"] == 1
    original_journal = journal.read_bytes()
    result = CLEANUP.execute([pin], receipt, ["fictional"])
    assert result["removed"] == 0
    assert result["already_absent"] == 1
    assert journal.read_bytes().startswith(original_journal)
    assert retained.read_bytes() == b"fictional retained backup"
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [event["event"] for event in events[:4]] == [
        "begin",
        "unlink_intent",
        "unlinked",
        "complete",
    ]
