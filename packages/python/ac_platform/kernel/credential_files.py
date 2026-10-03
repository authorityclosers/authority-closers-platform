"""Privacy check for confidential files, including systemd `LoadCredential` delivery.

systemd delivers a credential to a `User=` unit as a root-owned 0400 file plus one
POSIX ACL entry for the service uid. The ACL mask then shows in stat as mode 0440,
although the owning group has no access. Only that exact shape is accepted beside
the plain "no group or other bits" rule; nothing here reads or reports file content.
"""

from __future__ import annotations

import os
import stat
import struct
import sys
from pathlib import Path

SYSTEMD_CREDENTIALS_ROOT = Path("/run/credentials")
CREDENTIAL_OWNER_UID = 0

_ACL_XATTR = "system.posix_acl_access"
_ACL_VERSION = 2
_ACL_USER_OBJ, _ACL_USER, _ACL_GROUP_OBJ, _ACL_MASK, _ACL_OTHER = 0x01, 0x02, 0x04, 0x10, 0x20
_ACL_READ = 4
_ACL_UNDEFINED_ID = 0xFFFFFFFF
_ACL_HEADER = struct.Struct("<I")
_ACL_ENTRY = struct.Struct("<HHI")
_ACL_BYTES = _ACL_HEADER.size + 5 * _ACL_ENTRY.size


def acl_is_uid_private(blob: bytes, uid: int) -> bool:
    """True only for `user::r, user:<uid>:r, group::-, mask::r, other::-`."""
    if uid <= 0 or len(blob) != _ACL_BYTES:
        return False
    if _ACL_HEADER.unpack_from(blob)[0] != _ACL_VERSION:
        return False
    return list(_ACL_ENTRY.iter_unpack(blob[_ACL_HEADER.size :])) == [
        (_ACL_USER_OBJ, _ACL_READ, _ACL_UNDEFINED_ID),
        (_ACL_USER, _ACL_READ, uid),
        (_ACL_GROUP_OBJ, 0, _ACL_UNDEFINED_ID),
        (_ACL_MASK, _ACL_READ, _ACL_UNDEFINED_ID),
        (_ACL_OTHER, 0, _ACL_UNDEFINED_ID),
    ]


def _trusted_directory(path: Path) -> bool:
    info = path.lstat()
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == CREDENTIAL_OWNER_UID
        and not info.st_mode & 0o022
    )


def is_private_to_process(path: Path, descriptor: int, info: os.stat_result) -> bool:
    """Whether the open file is readable by its owner and this process only.

    `info` is the fstat of `descriptor`, opened from `path` without following links.
    """
    if os.name == "nt" or not info.st_mode & 0o077:
        return True
    getxattr = getattr(os, "getxattr", None)
    if sys.platform != "linux" or getxattr is None:
        return False
    try:
        uid = os.geteuid()
        return (
            stat.S_IMODE(info.st_mode) == 0o440
            and info.st_uid in {CREDENTIAL_OWNER_UID, uid}
            and path.is_absolute()
            and ".." not in path.parts
            and path.parent.parent == SYSTEMD_CREDENTIALS_ROOT
            and _trusted_directory(SYSTEMD_CREDENTIALS_ROOT)
            and _trusted_directory(path.parent)
            # Linux bounds xattrs to 64 KiB; the parser accepts exactly 44 bytes.
            and acl_is_uid_private(getxattr(descriptor, _ACL_XATTR), uid)
        )
    except OSError:
        return False
