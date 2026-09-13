#!/usr/bin/env python3
"""Validate and project the release-owned hosted Sales Xray compose overlay.

The capability file is immutable release policy.  The activation descriptor
and its digest sidecar remain outside the release archive so they can be
materialized by the approval/operations lanes without putting credentials in
Git.  Every path and digest is checked before the installer gives it to
Compose; this module never sources an environment file or reads credential
contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

CAPABILITY_RELATIVE = {
    "staging": Path("capabilities/sales-xray-hosted-staging.json"),
    "production": Path("capabilities/sales-xray-hosted-production.json"),
}
OVERLAY_RELATIVE = Path("compose.sales-xray-hosted.yaml")
MAX_CAPABILITY_BYTES = 8192
MAX_ACTIVATION_BYTES = 64 * 1024
MAX_ENV_BYTES = 64 * 1024
MAX_REFERENCE_BYTES = 4 * 1024 * 1024
MAX_CHALLENGE_SECRET_BYTES = 4 * 1024
API_UID = 10001
API_GID = 0
CHALLENGE_SECRET_MODE = 0o400
CHALLENGE_SECRET_NAME = "challenge-secret"  # noqa: S105 - basename only
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RELEASE_ID = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_REF = re.compile(r"^(?:[A-Za-z0-9._/-]+@)?sha256:[0-9a-f]{64}\Z")
UNIT_NAME = re.compile(r"[a-z0-9][a-z0-9@._-]{0,126}\.service\Z")
ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
ENV_VALUE = re.compile(r"[A-Za-z0-9_./:@+%=-]+\Z")
ABSOLUTE_ENV_KEYS = {
    "AC_XRAY_SERVICE_CONFIG",
    "AC_XRAY_APPROVAL_FILE",
    "AC_XRAY_DATABASE_URL_FILE",
    "AC_XRAY_STORAGE_ROOT",
    "AC_XRAY_SCRATCH_ROOT",
    "AC_XRAY_NATIVE_SOCKET_DIR",
    "AC_XRAY_ELEVENLABS_IDENTITY_DIR",
    "AC_XRAY_GROQ_IDENTITY_DIR",
    "AC_XRAY_GEMINI_IDENTITY_DIR",
    "AC_XRAY_CHALLENGE_SECRET_FILE",
    "AC_XRAY_INFISICAL_BINARY",
}
ENV_KEYS = ABSOLUTE_ENV_KEYS | {
    "AC_XRAY_SERVICE_SHA256",
    "AC_XRAY_APPROVAL_SHA256",
    "AC_XRAY_ACQUISITION_ENABLED",
    "AC_XRAY_NATIVE_IMAGE_REF",
    "AC_XRAY_CHALLENGE_SITE_KEY",
    "AC_XRAY_ACQUISITION_POLICY_REVISION",
}


class ActivationError(RuntimeError):
    """A release policy or external activation input failed admission."""


def _fail(message: str) -> ActivationError:
    return ActivationError(f"hosted Sales Xray activation refused: {message}")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("duplicate JSON key")
        result[key] = value
    return result


def _trusted_metadata(info: os.stat_result, *, file: bool) -> None:
    """Require root-owned, non-writable metadata for external activation input."""

    if info.st_uid != 0:
        raise _fail("trusted activation paths must be root-owned")
    writable_bits = 0o222 if file else 0o022
    if stat.S_IMODE(info.st_mode) & writable_bits:
        raise _fail("trusted activation paths must not be writable")


def _regular_bytes(path: Path, limit: int, *, trusted: bool = False) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise _fail("absolute traversal-free path required")
    for ancestor in (*reversed(path.parents), path):
        try:
            info = ancestor.lstat()
        except FileNotFoundError as exc:
            raise _fail("activation path is missing") from exc
        if stat.S_ISLNK(info.st_mode):
            raise _fail("symbolic links are forbidden in activation paths")
        if ancestor != path and not stat.S_ISDIR(info.st_mode):
            raise _fail("activation path ancestor is not a directory")
        if trusted and os.name == "posix":
            _trusted_metadata(info, file=ancestor == path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise _fail("activation input must be a singly-linked regular file")
    if not 0 < info.st_size <= limit:
        raise _fail("activation input exceeds its bounded size")
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) != info.st_size:
        raise _fail("activation input changed while reading")
    return raw


def _json_file(path: Path, limit: int, *, trusted: bool = False) -> dict[str, Any]:
    raw = _regular_bytes(path, limit, trusted=trusted)
    try:
        value = json.loads(raw, object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise _fail("activation JSON is invalid") from exc
    if not isinstance(value, dict):
        raise _fail("activation JSON must contain an object")
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checked_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise _fail(f"{field} must be a lowercase SHA-256 digest")
    return value


def _checked_absolute(value: object, field: str) -> Path:
    if not isinstance(value, str):
        raise _fail(f"{field} must be an absolute path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise _fail(f"{field} must be absolute and traversal-free")
    return path


def _validate_challenge_secret_reference(value: object) -> None:
    """Validate the host file bind-mounted into the API without reading it."""

    path = _checked_absolute(value, "AC_XRAY_CHALLENGE_SECRET_FILE")
    if path.name != CHALLENGE_SECRET_NAME:
        raise _fail("upload challenge file must use the fixed challenge-secret name")
    for ancestor in (*reversed(path.parents), path):
        try:
            info = ancestor.lstat()
        except FileNotFoundError as exc:
            raise _fail("upload challenge file is missing") from exc
        except OSError as exc:
            raise _fail("upload challenge file metadata is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise _fail("upload challenge file paths must not contain symbolic links")
        if ancestor != path:
            if not stat.S_ISDIR(info.st_mode):
                raise _fail("upload challenge file ancestor is not a directory")
            if os.name == "posix":
                _trusted_metadata(info, file=False)
            continue
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_CHALLENGE_SECRET_BYTES
        ):
            raise _fail("upload challenge input must be a bounded regular file")
        if os.name == "posix" and (
            info.st_uid != API_UID
            or info.st_gid != API_GID
            or stat.S_IMODE(info.st_mode) != CHALLENGE_SECRET_MODE
        ):
            raise _fail("upload challenge file ownership or mode is not API-readable")


def _release_identity(release: Path) -> str:
    if (
        not release.is_absolute()
        or release.name == ""
        or RELEASE_ID.fullmatch(release.name) is None
    ):
        raise _fail("an exact immutable release directory is required")
    marker = release / "RELEASE-COMMIT"
    raw = _regular_bytes(marker, 41)
    expected = (release.name + "\n").encode("ascii")
    if raw != expected:
        raise _fail("release identity marker differs from its directory")
    return release.name


def _load_capability(release: Path, environment: str) -> tuple[dict[str, Any] | None, str]:
    release_id = _release_identity(release)
    if environment not in {"staging", "production"}:
        raise _fail("only staging or production is accepted")
    path = release / CAPABILITY_RELATIVE[environment]
    if not path.exists() and not path.is_symlink():
        return None, release_id
    value = _json_file(path, MAX_CAPABILITY_BYTES)
    expected_keys = {
        "schema_version",
        "environment",
        "enabled",
        "activation_file_template",
        "activation_sha256_file_template",
        "previous_release_policy",
    }
    if set(value) != expected_keys:
        raise _fail("capability fields differ from the reviewed schema")
    if (
        value["schema_version"] != "ac.sales_xray.hosted_policy/1"
        or value["environment"] != environment
        or type(value["enabled"]) is not bool
    ):
        raise _fail("capability identity or enabled type is invalid")
    if not value["enabled"]:
        if (
            value["activation_file_template"] is not None
            or value["activation_sha256_file_template"] is not None
        ):
            raise _fail("disabled capability must not carry activation templates")
        if value["previous_release_policy"] != "disabled":
            raise _fail("disabled capability has an invalid previous-release policy")
        return None, release_id
    for field in ("activation_file_template", "activation_sha256_file_template"):
        if not isinstance(value[field], str):
            raise _fail(f"{field} must be an absolute path template")
        if "{release_id}" not in value[field] or "{environment}" not in value[field]:
            raise _fail(f"{field} must bind both release and environment")
    if value["previous_release_policy"] != "exact_target_release":
        raise _fail("enabled capability requires exact_target_release policy")
    return value, release_id


def _resolve_template(value: object, field: str, release_id: str, environment: str) -> Path:
    if not isinstance(value, str):
        raise _fail(f"{field} must be a path template")
    rendered = value.replace("{release_id}", release_id).replace("{environment}", environment)
    if "{" in rendered or "}" in rendered:
        raise _fail(f"{field} contains an unsupported template expression")
    return _checked_absolute(rendered, field)


def _read_sidecar(path: Path) -> str:
    raw = _regular_bytes(path, 128, trusted=True)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise _fail("activation digest sidecar is not ASCII") from exc
    if re.fullmatch(r"[0-9a-f]{64}\n", text) is None:
        raise _fail("activation digest sidecar must contain one canonical SHA-256 line")
    return text[:-1]


def _checked_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise _fail(f"{field} must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise _fail(f"{field} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise _fail(f"{field} must be a canonical lowercase UUID")
    return value


def _parse_env(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("compose environment file is not UTF-8") from exc
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line or "=" not in line:
            raise _fail("compose environment must use assignment lines")
        key, value = line.split("=", 1)
        if ENV_KEY.fullmatch(key) is None or key not in ENV_KEYS:
            raise _fail("compose environment contains an unapproved key")
        if key in result or not value or ENV_VALUE.fullmatch(value) is None:
            raise _fail("compose environment contains a duplicate or unsafe value")
        result[key] = value
    if set(result) != ENV_KEYS:
        raise _fail("compose environment is incomplete")
    for key in ABSOLUTE_ENV_KEYS:
        path = _checked_absolute(result[key], key)
        if ".." in path.parts:
            raise _fail(f"{key} is traversal-prone")
    _validate_challenge_secret_reference(result["AC_XRAY_CHALLENGE_SECRET_FILE"])
    for key in ("AC_XRAY_SERVICE_SHA256", "AC_XRAY_APPROVAL_SHA256"):
        _checked_sha(result[key], key)
    if result["AC_XRAY_ACQUISITION_ENABLED"] not in {"true", "false"}:
        raise _fail("AC_XRAY_ACQUISITION_ENABLED must be the literal true or false")
    if IMAGE_REF.fullmatch(result["AC_XRAY_NATIVE_IMAGE_REF"]) is None:
        raise _fail("native image environment reference is not immutable")
    if re.fullmatch(r"[A-Za-z0-9_-]{3,256}", result["AC_XRAY_CHALLENGE_SITE_KEY"]) is None:
        raise _fail("upload challenge site key is invalid")
    revision = result["AC_XRAY_ACQUISITION_POLICY_REVISION"]
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", revision) is None:
        raise _fail("acquisition policy revision is invalid")
    return result


def _validate_service_mode(
    service: dict[str, Any], env: dict[str, str], approval: dict[str, Any]
) -> None:
    """Bind the worker posture, API acquisition flag and approval artifact."""

    bootstrap_only = service.get("bootstrap_only", False)
    if type(bootstrap_only) is not bool:
        raise _fail("service.bootstrap_only must be a boolean")
    providers = service.get("providers")
    if not isinstance(providers, list):
        raise _fail("service.providers must be a list")
    acquisition_enabled = env["AC_XRAY_ACQUISITION_ENABLED"] == "true"
    if bootstrap_only and acquisition_enabled:
        raise _fail("bootstrap service must disable API acquisition")
    if not bootstrap_only and not acquisition_enabled:
        raise _fail("active worker must enable API acquisition")
    policy = approval.get("acquisition_policy")
    if bootstrap_only:
        if providers:
            raise _fail("bootstrap service must not configure providers")
        if approval.get("allowances") != [] or approval.get("stages") != []:
            raise _fail("bootstrap approval must have empty allowances and stages")
        if policy is not None:
            raise _fail("bootstrap approval must not contain an acquisition policy")
        if approval.get("budget_cap_paise", 0) != 0:
            raise _fail("bootstrap approval must have zero paid budget")
        if approval.get("paid_approval_ref") is not None:
            raise _fail("bootstrap approval must not contain paid approval")
    elif not providers:
        raise _fail("active worker must configure at least one provider")


def _load_activation(
    value: dict[str, Any],
    release: Path,
    release_id: str,
    environment: str,
    managed_operations_tenant: str,
) -> tuple[Path, Path]:
    expected_keys = {
        "schema_version",
        "environment",
        "release_id",
        "compose_overlay",
        "compose_profile",
        "compose_env_file",
        "compose_env_sha256",
        "service_config_file",
        "service_config_sha256",
        "approval_file",
        "approval_sha256",
        "native_image_ref",
        "native_image_config_id",
        "helper_unit",
        "previous_release_policy",
    }
    if set(value) != expected_keys:
        raise _fail("activation descriptor fields differ from the reviewed schema")
    if (
        value["schema_version"] != "ac.sales_xray.hosted_activation/1"
        or value["environment"] != environment
        or value["release_id"] != release_id
        or value["compose_overlay"] != OVERLAY_RELATIVE.as_posix()
        or value["compose_profile"] != "sales-xray-hosted"
        or value["previous_release_policy"] != "exact_target_release"
    ):
        raise _fail("activation descriptor identity or policy is invalid")
    if not isinstance(value["native_image_ref"], str) or IMAGE_REF.fullmatch(
        value["native_image_ref"]
    ) is None:
        raise _fail("native_image_ref must be immutable")
    if not isinstance(value["native_image_config_id"], str) or IMAGE_REF.fullmatch(
        value["native_image_config_id"]
    ) is None:
        raise _fail("native_image_config_id must be immutable")
    if not isinstance(value["helper_unit"], str) or UNIT_NAME.fullmatch(
        value["helper_unit"]
    ) is None:
        raise _fail("helper_unit must be a fixed systemd service name")

    overlay = release / OVERLAY_RELATIVE
    expected_overlay = Path(value["compose_overlay"])
    if expected_overlay != OVERLAY_RELATIVE or not overlay.is_file() or overlay.is_symlink():
        raise _fail("the source-owned hosted compose overlay is unavailable")
    env_path = _checked_absolute(value["compose_env_file"], "compose_env_file")
    env_raw = _regular_bytes(env_path, MAX_ENV_BYTES, trusted=True)
    if _sha256(env_raw) != _checked_sha(value["compose_env_sha256"], "compose_env_sha256"):
        raise _fail("compose environment digest differs from the descriptor")
    env = _parse_env(env_raw)
    if env["AC_XRAY_NATIVE_IMAGE_REF"] != value["native_image_ref"]:
        raise _fail("API preflight image differs from the worker native image")
    for path_field, env_key in (
        ("service_config_file", "AC_XRAY_SERVICE_CONFIG"),
        ("approval_file", "AC_XRAY_APPROVAL_FILE"),
    ):
        expected = _checked_absolute(value[path_field], path_field)
        if Path(env[env_key]) != expected:
            raise _fail(f"{env_key} differs from the activation descriptor")
    service_path = _checked_absolute(value["service_config_file"], "service_config_file")
    service_raw = _regular_bytes(service_path, MAX_REFERENCE_BYTES, trusted=True)
    if _sha256(service_raw) != _checked_sha(
        value["service_config_sha256"], "service_config_sha256"
    ):
        raise _fail("service config digest differs from the descriptor")
    if env["AC_XRAY_SERVICE_SHA256"] != value["service_config_sha256"]:
        raise _fail("service config compose digest differs from the descriptor")
    service = _json_file(service_path, MAX_REFERENCE_BYTES, trusted=True)
    if (
        service.get("schema_version") != "ac.sales_xray.worker_service/1"
        or service.get("sales_xray_enabled") is not True
        or service.get("release_id") != release_id
        or service.get("environment") != environment
        or service.get("sales_xray_approval_path") != "/run/ac-sales-xray/approval.json"
        or service.get("sales_xray_approval_sha256")
        != _checked_sha(value["approval_sha256"], "approval_sha256")
        or service.get("sales_xray_storage_root") != env["AC_XRAY_STORAGE_ROOT"]
        or service.get("sales_xray_scratch_root") != env["AC_XRAY_SCRATCH_ROOT"]
        or service.get("database_url_file") != "/run/ac-sales-xray/database-url"
        or service.get("native_socket_path")
        != env["AC_XRAY_NATIVE_SOCKET_DIR"].rstrip("/") + "/native.sock"
        or service.get("native_image_ref") != value["native_image_ref"]
    ):
        raise _fail("service config is not bound to the reviewed mounts and image")
    operations_tenant = _checked_uuid(
        service.get("operations_tenant_id"), "service.operations_tenant_id"
    )
    if operations_tenant != managed_operations_tenant:
        raise _fail("service operations tenant differs from managed runtime scope")
    approval_path = _checked_absolute(value["approval_file"], "approval_file")
    approval_raw = _regular_bytes(approval_path, MAX_REFERENCE_BYTES, trusted=True)
    if _sha256(approval_raw) != _checked_sha(value["approval_sha256"], "approval_sha256"):
        raise _fail("approval digest differs from the descriptor")
    if env["AC_XRAY_APPROVAL_SHA256"] != value["approval_sha256"]:
        raise _fail("approval compose digest differs from the descriptor")
    approval = _json_file(approval_path, MAX_REFERENCE_BYTES, trusted=True)
    if (
        approval.get("schema") != "ac.sales-xray.hosted-approval/1"
        or approval.get("environment") != environment
    ):
        raise _fail("approval is not bound to the selected environment")
    if _checked_uuid(
        approval.get("provider_control_tenant_id"),
        "approval.provider_control_tenant_id",
    ) != operations_tenant:
        raise _fail("approval control tenant differs from service operations tenant")
    _validate_service_mode(service, env, approval)
    return overlay, env_path


def compose_inputs(
    release: Path, environment: str, operations_tenant_id: str | None = None
) -> tuple[Path, Path, str] | None:
    capability, release_id = _load_capability(release, environment)
    if capability is None:
        return None
    managed_operations_tenant = _checked_uuid(
        operations_tenant_id, "managed AC_OPERATIONS_TENANT_ID"
    )
    activation_path = _resolve_template(
        capability["activation_file_template"],
        "activation_file_template",
        release_id,
        environment,
    )
    digest_path = _resolve_template(
        capability["activation_sha256_file_template"],
        "activation_sha256_file_template",
        release_id,
        environment,
    )
    activation_raw = _regular_bytes(activation_path, MAX_ACTIVATION_BYTES, trusted=True)
    expected_sha = _read_sidecar(digest_path)
    if _sha256(activation_raw) != expected_sha:
        raise _fail("activation descriptor digest differs from the release policy")
    descriptor = _json_file(activation_path, MAX_ACTIVATION_BYTES, trusted=True)
    overlay, env_path = _load_activation(
        descriptor,
        release,
        release_id,
        environment,
        managed_operations_tenant,
    )
    return overlay, env_path, descriptor["compose_profile"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("compose-inputs",))
    parser.add_argument("release", type=Path)
    parser.add_argument("environment", choices=("staging", "production"))
    parser.add_argument("--operations-tenant-id")
    args = parser.parse_args(argv)
    try:
        result = compose_inputs(
            args.release, args.environment, args.operations_tenant_id
        )
        if result is not None:
            for value in result:
                print(value)
    except (ActivationError, OSError, ValueError, TypeError, KeyError):
        print("FAIL  Hosted Sales Xray activation validation failed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
