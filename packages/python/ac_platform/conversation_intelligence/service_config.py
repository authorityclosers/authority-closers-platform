"""Non-secret, release-pinned configuration for the dedicated hosted worker.

This does not load the API Settings object, a dotenv file, browser identity, or
provider keys. Only the service's database credential is read by this process.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONFIG_BYTES = 64 * 1024


def absolute_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("worker_path_invalid")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("worker_path_invalid")
    return value


def read_private_file(path: Path, *, limit: int, confidential: bool = False) -> bytes:
    """Read a bounded regular file with stable errors and no payload logging."""
    try:
        absolute_path(str(path))
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            forbidden_mode = 0o077 if confidential else 0o022
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not 0 < info.st_size <= limit
                or (os.name != "nt" and info.st_mode & forbidden_mode)
            ):
                raise ValueError
            result = stream.read(limit + 1)
            if not 0 < len(result) <= limit:
                raise ValueError
            return result
    except (OSError, ValueError):
        raise ValueError("worker_file_unavailable") from None


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class ProviderLauncherConfig(StrictConfig):
    credential_ref: Annotated[str, Field(pattern=r"^ref:[A-Za-z0-9_./:-]{1,200}$")]
    provider_id: Literal["elevenlabs", "deepgram", "groq", "gemini"]
    executable: str
    project_ref: str
    environment_ref: str
    secret_path_ref: str
    token_file_ref: str

    _paths = field_validator("executable", "token_file_ref")(absolute_path)


class WorkerServiceConfig(StrictConfig):
    schema_version: Literal["ac.sales_xray.worker_service/1"]
    environment: Literal["staging", "production"]
    release_id: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    operations_tenant_id: UUID
    sales_xray_enabled: Literal[True] = True
    # Explicit migration bootstrap only.  It is a release-owned, temporary
    # service posture; the normal worker remains provider-backed by default.
    bootstrap_only: bool = False
    sales_xray_approval_path: str
    sales_xray_approval_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    sales_xray_storage_root: str
    sales_xray_scratch_root: str
    database_url_file: str
    native_socket_path: str
    native_image_ref: Annotated[str, Field(pattern=r"^(?:[A-Za-z0-9._/-]+@)?sha256:[0-9a-f]{64}$")]
    providers: Annotated[list[ProviderLauncherConfig], Field(min_length=0, max_length=4)]

    @field_validator("operations_tenant_id", mode="before")
    @classmethod
    def canonical_operations_tenant(cls, value: Any) -> UUID:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            parsed = UUID(value)
            if str(parsed) == value:
                return parsed
        raise ValueError("worker_operations_tenant_invalid")

    _paths = field_validator(
        "sales_xray_approval_path",
        "sales_xray_storage_root",
        "sales_xray_scratch_root",
        "database_url_file",
        "native_socket_path",
    )(absolute_path)

    @model_validator(mode="after")
    def validate_scopes(self) -> Self:
        roots = [Path(self.sales_xray_storage_root), Path(self.sales_xray_scratch_root)]
        if roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):
            raise ValueError("worker_storage_scope_invalid")
        credentials = [self.database_url_file, *(p.token_file_ref for p in self.providers)]
        if len(set(credentials)) != len(credentials):
            raise ValueError("worker_identity_scope_invalid")
        if any(Path(value).is_relative_to(root) for value in credentials for root in roots):
            raise ValueError("worker_identity_scope_invalid")
        if len({p.credential_ref for p in self.providers}) != len(self.providers):
            raise ValueError("worker_provider_scope_invalid")
        if len({p.provider_id for p in self.providers}) != len(self.providers):
            raise ValueError("worker_provider_scope_invalid")
        if self.bootstrap_only:
            if self.providers:
                raise ValueError("worker_bootstrap_providers_forbidden")
        elif not self.providers:
            raise ValueError("worker_providers_required")
        return self


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("worker_config_invalid")
        value[key] = item
    return value


def load_service_config(path: Path, sha256: str) -> WorkerServiceConfig:
    try:
        if not _SHA.fullmatch(sha256):
            raise ValueError
        raw = read_private_file(path, limit=_MAX_CONFIG_BYTES)
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_unique_object)
        return WorkerServiceConfig.model_validate(value)
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("worker_config_invalid") from None


def verify_installed_release(config: WorkerServiceConfig, marker: Path) -> None:
    if read_private_file(marker, limit=64).strip() != config.release_id.encode("ascii"):
        raise ValueError("worker_release_mismatch")


def load_database_url(path: Path) -> URL:
    """Runtime-only read; URLs and exception payloads never leave this boundary."""
    try:
        value = read_private_file(path, limit=4096, confidential=True).decode("utf-8").strip()
        url = make_url(value)
        if (
            url.drivername != "postgresql+psycopg"
            or url.username != "ac_runtime"
            or url.database != "ac_platform"
            or not url.host
            or url.host in {"localhost", "127.0.0.1", "::1"}
            or not url.password
            or len(url.password) < 16
            or url.password.startswith("local-")
            or set(url.query) - {"sslmode"}
        ):
            raise ValueError
        return url
    except (ValueError, TypeError, UnicodeError, ArgumentError):
        raise ValueError("worker_database_configuration_invalid") from None
