"""Immutable release identity supplied by the reviewed API image."""

from __future__ import annotations

import re
from pathlib import Path

BAKED_RELEASE_ID_PATH = Path("/app/.ac-release-id")
_RELEASE_ID = re.compile(r"^[0-9a-f]{40}$")


class ReleaseIdentityError(RuntimeError):
    """The API image does not contain one valid baked release identity."""


def read_baked_release_id() -> str:
    """Return the build-time Git SHA, failing closed on an absent or altered marker."""

    if BAKED_RELEASE_ID_PATH.is_symlink():
        raise ReleaseIdentityError("baked API release marker must not be a symbolic link")
    try:
        marker = BAKED_RELEASE_ID_PATH.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise ReleaseIdentityError("baked API release marker is unavailable") from error
    release_id = marker.removesuffix("\n")
    if marker != f"{release_id}\n" or _RELEASE_ID.fullmatch(release_id) is None:
        raise ReleaseIdentityError("baked API release marker is malformed")
    return release_id


def require_baked_release_id(runtime_release_id: str) -> str:
    """Require a deployment runtime to identify as its immutable image build."""

    baked_release_id = read_baked_release_id()
    if runtime_release_id != baked_release_id:
        raise ReleaseIdentityError(
            "runtime AC_RELEASE_ID does not match the baked API release marker"
        )
    return baked_release_id


__all__ = ["ReleaseIdentityError", "read_baked_release_id", "require_baked_release_id"]
