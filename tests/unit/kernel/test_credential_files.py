from __future__ import annotations

import errno
import os
import stat
import struct
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import ac_platform.kernel.credential_files as credential_files
from ac_platform.conversation_intelligence.service_config import (
    load_database_url,
    read_private_file,
)
from ac_platform.http.conversation_acquisition_runtime import _challenge_secret
from ac_platform.kernel.credential_files import acl_is_uid_private, is_private_to_process

UNDEFINED = 0xFFFFFFFF
USER_OBJ, USER, GROUP_OBJ, GROUP, MASK, OTHER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
# Byte-exact systemd LoadCredential ACL for User=10001 (Linux xattr encoding).
SYSTEMD_UID_10001_ACL = bytes.fromhex(
    "0200000001000400ffffffff020004001127000004000000ffffffff10000400ffffffff20000000ffffffff"
)
# Synthetic values exercise parsing only; no service is contacted.
DATABASE_URL = b"postgresql+psycopg://ac_runtime:synthetic-test-value@db/ac_platform"
CHALLENGE = b"synthetic-challenge-placeholder\n"

Entry = tuple[int, int, int]


def acl(*entries: Entry, version: int = 2) -> bytes:
    return struct.pack("<I", version) + b"".join(struct.pack("<HHI", *entry) for entry in entries)


def private_entries(uid: int) -> list[Entry]:
    return [
        (USER_OBJ, 4, UNDEFINED),
        (USER, 4, uid),
        (GROUP_OBJ, 0, UNDEFINED),
        (MASK, 4, UNDEFINED),
        (OTHER, 0, UNDEFINED),
    ]


def changed(uid: int, index: int, entry: Entry) -> bytes:
    entries = private_entries(uid)
    entries[index] = entry
    return acl(*entries)


def inserted(uid: int, index: int, entry: Entry) -> bytes:
    entries = private_entries(uid)
    entries.insert(index, entry)
    return acl(*entries)


def test_exact_systemd_acl_is_private_to_the_service_uid() -> None:
    assert acl(*private_entries(10001)) == SYSTEMD_UID_10001_ACL
    assert acl_is_uid_private(SYSTEMD_UID_10001_ACL, 10001)


@pytest.mark.parametrize(
    "blob",
    [
        changed(10001, 2, (GROUP_OBJ, 4, UNDEFINED)),
        changed(10001, 4, (OTHER, 4, UNDEFINED)),
        changed(10001, 1, (USER, 4, 10002)),
        changed(10001, 1, (USER, 4, 0)),
        inserted(10001, 2, (USER, 4, 10002)),
        inserted(10001, 3, (GROUP, 4, 10001)),
        changed(10001, 1, (GROUP, 4, 10001)),
        changed(10001, 3, (MASK, 6, UNDEFINED)),
        changed(10001, 0, (USER_OBJ, 6, UNDEFINED)),
        changed(10001, 1, (USER, 6, 10001)),
        changed(10001, 0, (USER_OBJ, 4, 10001)),
        changed(10001, 2, (GROUP_OBJ, 0, 10001)),
        changed(10001, 3, (MASK, 4, 10001)),
        changed(10001, 4, (OTHER, 0, 10001)),
        acl(*private_entries(10001), version=1),
        acl(*private_entries(10001)[:4]),
        acl(*reversed(private_entries(10001))),
        SYSTEMD_UID_10001_ACL[:-1],
        SYSTEMD_UID_10001_ACL + b"\x00",
        b"",
    ],
    ids=[
        "group-readable",
        "other-readable",
        "unrelated-uid",
        "root-named",
        "second-named-user",
        "named-group",
        "group-instead-of-user",
        "mask-rw",
        "owner-rw",
        "named-user-rw",
        "owner-defined-id",
        "group-defined-id",
        "mask-defined-id",
        "other-defined-id",
        "version-1",
        "no-other-entry",
        "wrong-order",
        "truncated",
        "trailing-byte",
        "empty",
    ],
)
def test_any_other_acl_is_rejected(blob: bytes) -> None:
    assert not acl_is_uid_private(blob, 10001)


def test_acl_is_never_private_to_another_or_root_process() -> None:
    assert not acl_is_uid_private(SYSTEMD_UID_10001_ACL, 10002)
    assert not acl_is_uid_private(acl(*private_entries(0)), 0)


pytestmark_linux = pytest.mark.skipif(
    sys.platform != "linux",
    reason="needs Linux POSIX ACLs",
)


@pytest.mark.parametrize("control", ["valid", "non-linux", "unrelated-owner", "root-process"])
def test_systemd_metadata_decision(monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    path = Path("/run/credentials/ac-dev-test.service/database-url")
    info = os.stat_result((stat.S_IFREG | 0o440, 1, 1, 1, 0, 0, 64, 0, 0, 0))
    directory = os.stat_result((stat.S_IFDIR | 0o755, 1, 1, 1, 0, 0, 0, 0, 0, 0))
    monkeypatch.setattr(credential_files, "SYSTEMD_CREDENTIALS_ROOT", path.parent.parent)
    monkeypatch.setattr(credential_files, "CREDENTIAL_OWNER_UID", 0)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "geteuid", lambda: 10001, raising=False)
    monkeypatch.setattr(Path, "lstat", lambda _: directory)

    def getxattr(fd: int, name: str) -> bytes:
        assert fd == 123 and name == "system.posix_acl_access"
        return SYSTEMD_UID_10001_ACL

    monkeypatch.setattr(os, "getxattr", getxattr, raising=False)
    if control == "non-linux":
        monkeypatch.setattr(sys, "platform", "darwin")
    elif control == "unrelated-owner":
        info = os.stat_result((stat.S_IFREG | 0o440, 1, 1, 1, 10002, 0, 64, 0, 0, 0))
    elif control == "root-process":
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert is_private_to_process(path, 123, info) == (control == "valid")


def set_acl(path: Path, blob: bytes) -> None:
    try:
        os.setxattr(path, "system.posix_acl_access", blob)
    except OSError as error:
        if error.errno == errno.ENOTSUP:
            pytest.skip("filesystem has no POSIX ACL support")
        raise


@pytest.fixture
def deliver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Mimic `/run/credentials/<unit>/<name>`: 0400 file, then the ACL systemd adds."""
    root = tmp_path / "credentials"
    monkeypatch.setattr(credential_files, "SYSTEMD_CREDENTIALS_ROOT", root)
    monkeypatch.setattr(credential_files, "CREDENTIAL_OWNER_UID", os.geteuid())

    def _deliver(
        content: bytes, blob: bytes | None, *, base: Path = root, mode: int | None = None
    ) -> Path:
        unit = base / "ac-dev-test.service"
        unit.mkdir(parents=True, mode=0o700)
        base.chmod(0o755)
        path = unit / "credential"
        path.write_bytes(content)
        path.chmod(0o400)
        if blob is not None:
            set_acl(path, blob)
        if mode is not None:
            path.chmod(mode)
        return path

    return _deliver


def read_database(path: Path) -> None:
    assert load_database_url(path).username == "ac_runtime"


def read_challenge(path: Path) -> None:
    assert _challenge_secret(path).get_secret_value() == CHALLENGE.decode().strip()


READERS = [
    pytest.param(read_database, DATABASE_URL, "worker_database_configuration_invalid", id="db"),
    pytest.param(read_challenge, CHALLENGE, "acquisition_challenge_unavailable", id="challenge"),
]
Reader = Callable[[Path], None]


def rejected(reader: Reader, path: Path, code: str) -> None:
    with pytest.raises(ValueError) as caught:
        reader(path)
    assert str(caught.value) == code
    assert "synthetic" not in str(caught.value) and str(path) not in str(caught.value)


@pytestmark_linux
@pytest.mark.parametrize(("reader", "content", "code"), READERS)
def test_readers_accept_real_uid_private_delivery_and_reject_it_without_the_acl(
    deliver: Callable[..., Path], reader: Reader, content: bytes, code: str
) -> None:
    path = deliver(content, acl(*private_entries(os.geteuid())))
    assert path.stat().st_mode & 0o777 == 0o440
    reader(path)
    os.removexattr(path, "system.posix_acl_access")
    path.chmod(0o440)
    rejected(reader, path, code)
    path.chmod(0o400)
    reader(path)


@pytestmark_linux
@pytest.mark.parametrize(("reader", "content", "code"), READERS)
@pytest.mark.parametrize(
    "kind",
    [
        "group-readable",
        "other-readable",
        "unrelated-uid",
        "second-named-user",
        "named-group",
        "mask-rw",
        "plain-0440",
        "plain-0444",
        "untrusted-path",
        "group-writable-parent",
        "other-writable-root",
        "symlink",
        "symlinked-unit",
        "hard-link",
    ],
)
def test_readers_reject_every_other_shared_shape(
    deliver: Callable[..., Path],
    tmp_path: Path,
    kind: str,
    reader: Reader,
    content: bytes,
    code: str,
) -> None:
    uid = os.geteuid()
    private = acl(*private_entries(uid))
    blobs = {
        "group-readable": changed(uid, 2, (GROUP_OBJ, 4, UNDEFINED)),
        "other-readable": changed(uid, 4, (OTHER, 4, UNDEFINED)),
        "unrelated-uid": changed(uid, 1, (USER, 4, uid + 1)),
        "second-named-user": inserted(uid, 2, (USER, 4, uid + 1)),
        "named-group": inserted(uid, 3, (GROUP, 4, os.getegid())),
        "mask-rw": changed(uid, 3, (MASK, 6, UNDEFINED)),
    }
    if kind in blobs:
        path = deliver(content, blobs[kind])
    elif kind in {"plain-0440", "plain-0444"}:
        path = deliver(content, None, mode=int(kind[-4:], 8))
    elif kind == "untrusted-path":
        path = deliver(content, private, base=tmp_path / "elsewhere")
    else:
        path = deliver(content, private)
        reader(path)
        if kind == "group-writable-parent":
            path.parent.chmod(0o770)
        elif kind == "other-writable-root":
            path.parent.parent.chmod(0o757)
        elif kind == "symlink":
            link = path.with_name("alias")
            link.symlink_to(path)
            path = link
        elif kind == "symlinked-unit":
            alias = path.parent.with_name("alias.service")
            alias.symlink_to(path.parent, target_is_directory=True)
            path = alias / path.name
        elif kind == "hard-link":
            os.link(path, path.with_name("second-name"))
    rejected(reader, path, code)


@pytestmark_linux
def test_directory_owner_must_be_the_credential_owner(
    deliver: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = deliver(DATABASE_URL, acl(*private_entries(os.geteuid())))
    read_database(path)
    monkeypatch.setattr(credential_files, "CREDENTIAL_OWNER_UID", 0)
    rejected(read_database, path, "worker_database_configuration_invalid")


@pytestmark_linux
def test_missing_xattr_support_is_a_rejection(
    deliver: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = deliver(DATABASE_URL, acl(*private_entries(os.geteuid())))
    descriptor = os.open(path, os.O_RDONLY)
    try:
        info = os.fstat(descriptor)
        assert is_private_to_process(path, descriptor, info)

        def unsupported(*_: object) -> bytes:
            raise OSError(errno.ENOTSUP, "unsupported")

        monkeypatch.setattr(os, "getxattr", unsupported)
        assert not is_private_to_process(path, descriptor, info)
        monkeypatch.delattr(os, "getxattr")
        assert not is_private_to_process(path, descriptor, info)
    finally:
        os.close(descriptor)


def test_non_confidential_branch_still_allows_group_and_other_read(tmp_path: Path) -> None:
    path = tmp_path / "marker"
    path.write_bytes(b"release")
    path.chmod(0o444)
    assert read_private_file(path, limit=64) == b"release"
    with pytest.raises(ValueError, match="^worker_file_unavailable$"):
        read_private_file(path, limit=64, confidential=True)
    path.chmod(0o664)
    with pytest.raises(ValueError, match="^worker_file_unavailable$"):
        read_private_file(path, limit=64)
