#!/usr/bin/env python3
"""Prepare a new hosted Sales Xray activation bundle without activating it.

This command is deliberately offline and prepare-only.  It verifies an
existing activation descriptor and its referenced, digest-bound environment,
service, and approval artifacts; verifies an immutable native-image manifest;
then writes a fresh descriptor, service file, and compose environment file to
an operator-selected output directory.  It never writes the source files,
the live configuration directory, a database, or a secret.

By default, the generated approval reference and approval digest are carried
forward unchanged.  For a new release only, an operator may instead supply a
separately approved, digest-pinned replacement approval.  The complete hosted
approval contract is validated before the exact input bytes are copied into
the fresh output bundle.  Source files are never changed.  The canonical
installer remains responsible for copying/reviewing these prepared artifacts
and for activation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")
ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
ENV_VALUE = re.compile(r"[A-Za-z0-9_./:@+%=-]+\Z")

MAX_ACTIVATION_BYTES = 64 * 1024
MAX_REFERENCE_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
ENVIRONMENT_NAMES = frozenset({"staging", "production"})
OVERLAY = "compose.sales-xray-hosted.yaml"
OPENAI_OVERLAY = "compose.sales-xray-hosted-openai.yaml"
PROFILE = "sales-xray-hosted"
OPENAI_HOST_IDENTITY_DIR = PurePosixPath(
    "/etc/authority-closers/secrets/sales-xray/identities/openai"
)
OPENAI_TOKEN_FILE = "/run/ac-sales-xray/identities/openai/token"  # noqa: S105 - path only

ABSOLUTE_ENV_KEYS = frozenset(
    {
        "AC_XRAY_SERVICE_CONFIG",
        "AC_XRAY_APPROVAL_FILE",
        "AC_XRAY_DATABASE_URL_FILE",
        "AC_XRAY_STORAGE_ROOT",
        "AC_XRAY_SCRATCH_ROOT",
        "AC_XRAY_NATIVE_SOCKET_DIR",
        "AC_XRAY_ELEVENLABS_IDENTITY_DIR",
        "AC_XRAY_DEEPGRAM_IDENTITY_DIR",
        "AC_XRAY_GROQ_IDENTITY_DIR",
        "AC_XRAY_GEMINI_IDENTITY_DIR",
        "AC_XRAY_CHALLENGE_SECRET_FILE",
        "AC_XRAY_INFISICAL_BINARY",
    }
)
OPTIONAL_IDENTITY_ENV_KEYS = frozenset({"AC_XRAY_OPENAI_IDENTITY_DIR"})
ENV_KEYS = ABSOLUTE_ENV_KEYS | frozenset(
    {
        "AC_XRAY_SERVICE_SHA256",
        "AC_XRAY_APPROVAL_SHA256",
        "AC_XRAY_ACQUISITION_ENABLED",
        "AC_XRAY_NATIVE_IMAGE_REF",
        "AC_XRAY_CHALLENGE_SITE_KEY",
        "AC_XRAY_ACQUISITION_POLICY_REVISION",
    }
)

ACTIVATION_KEYS = frozenset(
    {
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
)


class PrepareError(RuntimeError):
    """A bounded input or output failed prepare-only admission."""


def _fail(message: str) -> PrepareError:
    return PrepareError(f"sales-xray native activation preparation refused: {message}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("duplicate JSON key")
        result[key] = value
    return result


def _read_bytes(path: Path, limit: int) -> bytes:
    """Read one bounded regular file without printing its contents.

    The source descriptor path is an operator-trusted reference.  Ownership
    and symlink policy belongs to the canonical installer; this offline tool
    intentionally avoids imposing POSIX-only metadata requirements so its
    output can be reviewed in a disposable test adapter.
    """

    if not path.is_absolute() or ".." in path.parts:
        raise _fail("input paths must be absolute and traversal-free")
    try:
        if not path.is_file():
            raise _fail("input path is not a regular file")
        size = path.stat().st_size
        if not 0 < size <= limit:
            raise _fail("input file is empty or exceeds its bounded size")
        raw = path.read_bytes()
    except OSError as exc:
        raise _fail("input file cannot be read") from exc
    if len(raw) != size:
        raise _fail("input file changed while being read")
    return raw


def _json(path: Path, limit: int) -> tuple[dict[str, Any], bytes]:
    raw = _read_bytes(path, limit)
    try:
        value = json.loads(raw, object_pairs_hook=_pairs_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise _fail("JSON input is invalid") from exc
    if not isinstance(value, dict):
        raise _fail("JSON input must contain an object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise _fail(f"{field} must be a lowercase SHA-256 digest")
    return value


def _image(value: object, field: str) -> str:
    if not isinstance(value, str) or IMAGE_REF.fullmatch(value) is None:
        raise _fail(f"{field} must be an immutable sha256 image reference")
    return value


def _release(value: object, field: str = "release_id") -> str:
    if not isinstance(value, str) or SHA40.fullmatch(value) is None:
        raise _fail(f"{field} must be a lowercase 40-character release SHA")
    return value


def _absolute(value: object, field: str) -> Path:
    if not isinstance(value, str):
        raise _fail(f"{field} must be an absolute path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise _fail(f"{field} must be absolute and traversal-free")
    return path


def _openai_identity_dir(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise _fail("OpenAI identity directory must use its dedicated host path")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or path != OPENAI_HOST_IDENTITY_DIR:
        raise _fail("OpenAI identity directory must use its dedicated host path")
    return path


def _uuidish(value: object, field: str) -> None:
    # The hosted validator owns the canonical UUID check.  Keeping this
    # bounded here avoids importing a release-owned module during preparation.
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            value,
        )
        is None
    ):
        raise _fail(f"{field} must be a canonical lowercase UUID")


def _validate_openai_identity_selection(
    descriptor: Mapping[str, Any], env: Mapping[str, str], service: Mapping[str, Any]
) -> None:
    providers = service.get("providers")
    if not isinstance(providers, list) or any(not isinstance(item, dict) for item in providers):
        raise _fail("source service provider entries are invalid")
    has_openai = any(item.get("provider_id") == "openai" for item in providers)
    expected_overlay = OPENAI_OVERLAY if has_openai else OVERLAY
    if descriptor.get("compose_overlay") != expected_overlay:
        raise _fail("source provider set does not match its hosted compose overlay")
    if has_openai:
        if "AC_XRAY_OPENAI_IDENTITY_DIR" not in env:
            raise _fail("OpenAI provider requires its separately scoped identity directory")
        _openai_identity_dir(env["AC_XRAY_OPENAI_IDENTITY_DIR"])
        if any(
            item.get("provider_id") == "openai" and item.get("token_file_ref") != OPENAI_TOKEN_FILE
            for item in providers
        ):
            raise _fail("OpenAI token file must use its dedicated mounted identity path")
    elif "AC_XRAY_OPENAI_IDENTITY_DIR" in env:
        raise _fail("OpenAI identity directory is unexpected without an OpenAI provider")


def _parse_env(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("compose environment is not UTF-8") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            raise _fail("compose environment must use assignment lines")
        key, value = line.split("=", 1)
        if ENV_KEY.fullmatch(key) is None or key not in ENV_KEYS | OPTIONAL_IDENTITY_ENV_KEYS:
            raise _fail("compose environment contains an unapproved key")
        if key in values or not value or ENV_VALUE.fullmatch(value) is None:
            raise _fail("compose environment contains a duplicate or unsafe value")
        values[key] = value
    if frozenset(values) not in {
        frozenset(ENV_KEYS),
        frozenset(ENV_KEYS | OPTIONAL_IDENTITY_ENV_KEYS),
    }:
        raise _fail("compose environment is incomplete")
    for key in ABSOLUTE_ENV_KEYS | OPTIONAL_IDENTITY_ENV_KEYS:
        if key not in values:
            continue
        if key == "AC_XRAY_OPENAI_IDENTITY_DIR":
            _openai_identity_dir(values[key])
            continue
        _absolute(values[key], key)
    _digest(values["AC_XRAY_SERVICE_SHA256"], "AC_XRAY_SERVICE_SHA256")
    _digest(values["AC_XRAY_APPROVAL_SHA256"], "AC_XRAY_APPROVAL_SHA256")
    if values["AC_XRAY_ACQUISITION_ENABLED"] not in {"true", "false"}:
        raise _fail("AC_XRAY_ACQUISITION_ENABLED must be true or false")
    _image(values["AC_XRAY_NATIVE_IMAGE_REF"], "AC_XRAY_NATIVE_IMAGE_REF")
    if re.fullmatch(r"[A-Za-z0-9_-]{3,256}", values["AC_XRAY_CHALLENGE_SITE_KEY"]) is None:
        raise _fail("AC_XRAY_CHALLENGE_SITE_KEY is invalid")
    if (
        re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", values["AC_XRAY_ACQUISITION_POLICY_REVISION"])
        is None
    ):
        raise _fail("AC_XRAY_ACQUISITION_POLICY_REVISION is invalid")
    return values


def _load_source(
    source_activation: Path,
) -> tuple[dict[str, Any], bytes, dict[str, str], dict[str, Any], bytes, dict[str, Any], bytes]:
    descriptor, descriptor_raw = _json(source_activation, MAX_ACTIVATION_BYTES)
    if set(descriptor) != ACTIVATION_KEYS:
        raise _fail("source activation fields differ from the hosted schema")
    if descriptor.get("schema_version") != "ac.sales_xray.hosted_activation/1":
        raise _fail("source activation schema is invalid")
    environment = descriptor.get("environment")
    if environment not in ENVIRONMENT_NAMES:
        raise _fail("source activation environment is invalid")
    _release(descriptor.get("release_id"), "source release_id")
    if (
        descriptor.get("compose_overlay") not in {OVERLAY, OPENAI_OVERLAY}
        or descriptor.get("compose_profile") != PROFILE
    ):
        raise _fail("source activation compose binding is invalid")
    if descriptor.get("previous_release_policy") != "exact_target_release":
        raise _fail("source activation release policy is invalid")
    source_image = _image(descriptor.get("native_image_ref"), "native_image_ref")
    _image(descriptor.get("native_image_config_id"), "native_image_config_id")
    helper_unit = descriptor.get("helper_unit")
    if (
        not isinstance(helper_unit, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9@._-]{0,126}\.service", helper_unit) is None
    ):
        raise _fail("source helper_unit is invalid")

    env_path = _absolute(descriptor.get("compose_env_file"), "compose_env_file")
    env_raw = _read_bytes(env_path, MAX_REFERENCE_BYTES)
    if _sha(env_raw) != _digest(descriptor.get("compose_env_sha256"), "compose_env_sha256"):
        raise _fail("source compose environment digest differs from activation")
    env = _parse_env(env_raw)
    if env["AC_XRAY_NATIVE_IMAGE_REF"] != source_image:
        raise _fail("source API image differs from activation image")
    service_path = _absolute(descriptor.get("service_config_file"), "service_config_file")
    approval_path = _absolute(descriptor.get("approval_file"), "approval_file")
    if Path(env["AC_XRAY_SERVICE_CONFIG"]) != service_path:
        raise _fail("source service path differs from compose environment")
    if Path(env["AC_XRAY_APPROVAL_FILE"]) != approval_path:
        raise _fail("source approval path differs from compose environment")
    service, service_raw = _json(service_path, MAX_REFERENCE_BYTES)
    service_digest = _digest(descriptor.get("service_config_sha256"), "service_config_sha256")
    if _sha(service_raw) != service_digest or env["AC_XRAY_SERVICE_SHA256"] != service_digest:
        raise _fail("source service digest differs from activation")
    approval, approval_raw = _json(approval_path, MAX_REFERENCE_BYTES)
    approval_digest = _digest(descriptor.get("approval_sha256"), "approval_sha256")
    if _sha(approval_raw) != approval_digest or env["AC_XRAY_APPROVAL_SHA256"] != approval_digest:
        raise _fail("source approval digest differs from activation")
    if (
        approval.get("schema") != "ac.sales-xray.hosted-approval/1"
        or approval.get("environment") != environment
    ):
        raise _fail("source approval is not bound to the activation environment")
    if service.get("schema_version") != "ac.sales_xray.worker_service/1":
        raise _fail("source service schema is invalid")
    if (
        service.get("environment") != environment
        or service.get("release_id") != descriptor["release_id"]
    ):
        raise _fail("source service release binding is invalid")
    if service.get("sales_xray_enabled") is not True:
        raise _fail("source service is not enabled")
    if service.get("sales_xray_approval_path") != "/run/ac-sales-xray/approval.json":
        raise _fail("source service approval mount is invalid")
    if service.get("sales_xray_approval_sha256") != approval_digest:
        raise _fail("source service approval digest differs from activation")
    if service.get("native_image_ref") != source_image:
        raise _fail("source service image differs from activation")
    if not isinstance(service.get("providers"), list):
        raise _fail("source service providers must be a list")
    _uuidish(service.get("operations_tenant_id"), "service.operations_tenant_id")
    if approval.get("provider_control_tenant_id") != service.get("operations_tenant_id"):
        raise _fail("approval and service operations tenant differ")
    if service.get("bootstrap_only") is True and service.get("providers"):
        raise _fail("bootstrap service must not contain providers")
    if service.get("bootstrap_only") is False and not service.get("providers"):
        raise _fail("active service must contain approved providers")
    _validate_openai_identity_selection(descriptor, env, service)
    return descriptor, descriptor_raw, env, service, service_raw, approval, approval_raw


def _load_native_manifest(path: Path, supplied_sha256: str) -> tuple[str, str, str]:
    if SHA256.fullmatch(supplied_sha256) is None:
        raise _fail("native artifact digest is invalid")
    metadata, raw = _json(path, MAX_MANIFEST_BYTES)
    if _sha(raw) != supplied_sha256:
        raise _fail("native artifact digest differs from manifest")
    try:
        schema = metadata["schema"]
        source = metadata["source_commit"]
        dockerfile = metadata["dockerfile"]
        target = metadata["target"]
        platform = metadata["platform"]
        doctor = metadata["doctor"]
        image = metadata["image"]
        transport = metadata["transport"]
        helper = metadata["helper_source"]
        image_ref = image["expected_runtime_ref"]
        config_id = image["image_id"]
        if (
            schema != "ac.sales-xray.native-image/1"
            or not isinstance(source, str)
            or SHA40.fullmatch(source) is None
            or dockerfile != "infra/conversation-worker/Dockerfile"
            or target != "runtime"
            or platform != {"os": "linux", "architecture": "amd64"}
            or doctor != {"ffmpeg": True, "ffprobe": True, "provider_calls": False}
            or image["identity_type"] != "oci_transport_manifest"
            or transport["manifest_digest"] != image_ref
            or transport["config_digest"] != config_id
            or helper["entrypoint"] != "scripts/native_runtime_helper.py"
            or helper["pythonpath"] != "packages/python"
        ):
            raise _fail("native artifact schema or target is invalid")
        _image(image_ref, "native artifact image reference")
        _image(config_id, "native artifact config identity")
    except (KeyError, TypeError, ValueError):
        raise _fail("native artifact schema or image pair is invalid") from None
    return source, image_ref, config_id


def _hosted_approval_loader() -> tuple[Any, Any]:
    """Load the same strict approval parser used by the hosted application."""

    package_root = Path(__file__).resolve().parents[3] / "packages" / "python"
    if package_root.is_dir() and str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    try:
        from ac_platform.conversation_intelligence.activation_contract import (
            ActivationContractError,
            load_hosted_approval_bundle,
        )
    except ImportError as exc:
        raise _fail("hosted approval contract validator is unavailable") from exc
    return ActivationContractError, load_hosted_approval_bundle


def _validate_replacement_approval(
    raw: bytes,
    *,
    expected_sha256: str,
    environment: str,
    operations_tenant_id: str,
    service: Mapping[str, Any],
    now_epoch: int | None = None,
) -> None:
    """Require canonical, current approval bytes bound to this hosted service."""

    if _sha(raw) != expected_sha256:
        raise _fail("replacement approval digest differs from the supplied approval")
    contract_error, load_bundle = _hosted_approval_loader()
    try:
        bundle = load_bundle(raw)
    except contract_error as exc:
        raise _fail("replacement approval does not satisfy the hosted contract") from exc
    if bundle.to_json() != raw:
        raise _fail("replacement approval must use canonical hosted contract bytes")
    if bundle.environment != environment:
        raise _fail("replacement approval environment differs from the source activation")
    if str(bundle.provider_control_tenant_id) != operations_tenant_id:
        raise _fail("replacement approval tenant differs from the service operations tenant")
    try:
        now = int(time.time()) if now_epoch is None else now_epoch
        bundle.current(now, environment)
    except contract_error as exc:
        raise _fail("replacement approval is not current") from exc

    all_stages = list(bundle.stages)
    if bundle.acquisition_policy is not None:
        all_stages.extend(
            stage for stage_set in bundle.acquisition_policy.stage_sets() for stage in stage_set
        )
    if any(stage.expires_at_epoch <= now for stage in all_stages):
        raise _fail("replacement approval contains an expired provider scope")
    if any(item.zero_cost_basis == "synthetic" for item in all_stages):
        raise _fail("hosted replacement approval cannot contain synthetic provider scopes")
    if any(
        item.expires_at_epoch <= now or item.issued_at_epoch > now
        for item in bundle.acquisition_c5_benchmarks
    ) or any(
        item.expires_at_epoch <= now or item.issued_at_epoch > now
        for item in bundle.stage_call_supplements
    ):
        raise _fail("replacement approval contains an inactive bounded provider scope")

    providers = service.get("providers")
    if not isinstance(providers, list) or any(not isinstance(item, dict) for item in providers):
        raise _fail("replacement approval service providers are invalid")
    provider_by_id: dict[str, Mapping[str, Any]] = {}
    credential_refs: set[str] = set()
    for provider in providers:
        provider_id = provider.get("provider_id")
        credential_ref = provider.get("credential_ref")
        if (
            not isinstance(provider_id, str)
            or provider_id in provider_by_id
            or not isinstance(credential_ref, str)
            or credential_ref in credential_refs
        ):
            raise _fail("replacement approval service providers are ambiguous")
        provider_by_id[provider_id] = provider
        credential_refs.add(credential_ref)

    for stage in all_stages:
        configured_provider = provider_by_id.get(stage.provider_id)
        if (
            configured_provider is None
            or configured_provider.get("credential_ref") != stage.credential_ref
        ):
            raise _fail("replacement approval provider credential is not configured by the service")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _env_bytes(values: Mapping[str, str]) -> bytes:
    return "".join(f"{key}={values[key]}\n" for key in sorted(values)).encode("utf-8")


def _fresh_output_dir(output_dir: Path) -> None:
    if not output_dir.is_absolute() or ".." in output_dir.parts:
        raise _fail("output-dir must be absolute and traversal-free")
    if output_dir.exists():
        if not output_dir.is_dir() or any(output_dir.iterdir()):
            raise _fail("output-dir must be a new empty directory")
        return
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise _fail("output-dir cannot be created") from exc


def prepare(
    *,
    source_activation: Path,
    target_release_id: str,
    native_artifact_manifest: Path,
    native_artifact_sha256: str,
    output_dir: Path,
    approval_file: Path | None = None,
    approval_sha256: str | None = None,
    native_reuse_proof: Path | None = None,
    native_reuse_proof_sha256: str | None = None,
    source_repository: Path | None = None,
) -> dict[str, Any]:
    """Validate source inputs and write a new, inactive activation bundle."""

    target_release = _release(target_release_id, "target_release_id")
    if (approval_file is None) != (approval_sha256 is None):
        raise _fail("replacement approval path and digest must be supplied together")
    reuse_arguments = (native_reuse_proof, native_reuse_proof_sha256, source_repository)
    if any(value is not None for value in reuse_arguments) and any(
        value is None for value in reuse_arguments
    ):
        raise _fail("native reuse requires a proof, its digest and source repository together")
    descriptor, _descriptor_raw, env, service, _service_raw, _approval, _approval_raw = (
        _load_source(source_activation)
    )
    _source_commit, image_ref, config_id = _load_native_manifest(
        native_artifact_manifest, native_artifact_sha256
    )
    compatibility: dict[str, Any] | None = None
    if _source_commit != target_release:
        if (
            native_reuse_proof is None
            or native_reuse_proof_sha256 is None
            or source_repository is None
        ):
            raise _fail("native artifact source commit differs from target release")
        sibling_directory = str(Path(__file__).resolve().parent)
        if sibling_directory not in sys.path:
            sys.path.insert(0, sibling_directory)
        from native_artifact_compatibility import NativeCompatibilityError, verify_reuse

        try:
            compatibility = verify_reuse(
                repository_root=source_repository,
                proof_path=native_reuse_proof,
                proof_sha256=native_reuse_proof_sha256,
                native_manifest=native_artifact_manifest,
                native_manifest_sha256=native_artifact_sha256,
                target_release=target_release,
            )
        except NativeCompatibilityError as exc:
            raise _fail(f"native reuse proof refused: {exc}") from exc
    elif native_reuse_proof is not None:
        raise _fail("native reuse proof is unnecessary for an exact-source native artifact")
    replacement_approval_raw: bytes | None = None
    replacement_approval_digest: str | None = None
    if approval_file is not None and approval_sha256 is not None:
        if target_release == descriptor["release_id"]:
            raise _fail("replacement approval requires a new target release")
        replacement_approval_digest = _digest(approval_sha256, "replacement approval SHA-256")
        replacement_approval_raw = _read_bytes(approval_file, MAX_REFERENCE_BYTES)
        _validate_replacement_approval(
            replacement_approval_raw,
            expected_sha256=replacement_approval_digest,
            environment=descriptor["environment"],
            operations_tenant_id=service["operations_tenant_id"],
            service=service,
        )
    _fresh_output_dir(output_dir)
    environment = descriptor["environment"]
    artifact_prefix = native_artifact_sha256[:16]
    service_path = output_dir / f"service-{target_release}-native-{artifact_prefix}.json"
    env_path = output_dir / f"compose-{target_release}-native-{artifact_prefix}.env"
    activation_path = output_dir / f"activation-{target_release}.json"
    digest_path = output_dir / f"activation-{target_release}.json.sha256"
    if replacement_approval_raw is None or replacement_approval_digest is None:
        approval_output_path = Path(descriptor["approval_file"])
        approval_output_raw = None
        approval_output_digest = descriptor["approval_sha256"]
    else:
        approval_output_path = output_dir / (
            f"approval-{target_release}-{replacement_approval_digest[:16]}.json"
        )
        approval_output_raw = replacement_approval_raw
        approval_output_digest = replacement_approval_digest
    paths = [service_path, env_path, activation_path, digest_path]
    if approval_output_raw is not None:
        paths.append(approval_output_path)
    if any(path.exists() or path.is_symlink() for path in paths):
        raise _fail("output artifact already exists")

    next_service = dict(service)
    next_service["release_id"] = target_release
    next_service["native_image_ref"] = image_ref
    next_service["sales_xray_approval_sha256"] = approval_output_digest
    service_raw = _json_bytes(next_service)
    service_digest = _sha(service_raw)

    next_env = dict(env)
    next_env["AC_XRAY_SERVICE_CONFIG"] = str(service_path)
    next_env["AC_XRAY_SERVICE_SHA256"] = service_digest
    next_env["AC_XRAY_NATIVE_IMAGE_REF"] = image_ref
    next_env["AC_XRAY_APPROVAL_FILE"] = str(approval_output_path)
    next_env["AC_XRAY_APPROVAL_SHA256"] = approval_output_digest
    env_raw = _env_bytes(next_env)

    next_descriptor = dict(descriptor)
    next_descriptor.update(
        {
            "release_id": target_release,
            "compose_env_file": str(env_path),
            "compose_env_sha256": _sha(env_raw),
            "service_config_file": str(service_path),
            "service_config_sha256": service_digest,
            "native_image_ref": image_ref,
            "native_image_config_id": config_id,
            "approval_file": str(approval_output_path),
            "approval_sha256": approval_output_digest,
        }
    )
    descriptor_raw = _json_bytes(next_descriptor)
    digest_raw = (_sha(descriptor_raw) + "\n").encode("ascii")
    output_files: list[tuple[Path, bytes]] = [
        (service_path, service_raw),
        (env_path, env_raw),
        (activation_path, descriptor_raw),
        (digest_path, digest_raw),
    ]
    if approval_output_raw is not None:
        output_files.append((approval_output_path, approval_output_raw))
    compatibility_path: Path | None = None
    if compatibility is not None:
        compatibility_path = output_dir / f"native-compatibility-{target_release}.json"
        compatibility["activation_sha256"] = _sha(descriptor_raw)
        output_files.append((compatibility_path, _json_bytes(compatibility)))
    created_paths: list[Path] = []
    try:
        for path, raw in output_files:
            with path.open("xb") as output_file:
                created_paths.append(path)
                output_file.write(raw)
    except OSError as exc:
        # The output directory is disposable and created by this command.  A
        # best-effort cleanup prevents a caller from mistaking a partial set
        # for a reviewable bundle; source/live paths are never touched.
        for path in created_paths:
            with contextlib.suppress(OSError):
                path.unlink()
        raise _fail("output artifact write failed") from exc
    return {
        "environment": environment,
        "release_id": target_release,
        "native_source_commit": _source_commit,
        "native_image_ref": image_ref,
        "native_image_config_id": config_id,
        "native_compatibility_receipt": str(compatibility_path) if compatibility_path else None,
        "approval_file": str(approval_output_path),
        "approval_sha256": approval_output_digest,
        "approval_replaced": approval_output_raw is not None,
        "output_dir": str(output_dir),
        "activation": str(activation_path),
        "activation_sha256": str(digest_path),
        "service": str(service_path),
        "compose_env": str(env_path),
        "writes": len(output_files),
        "provider_calls": 0,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-activation", type=Path, required=True)
    parser.add_argument("--target-release-id", required=True)
    parser.add_argument("--native-artifact-manifest", type=Path, required=True)
    parser.add_argument("--native-artifact-sha256", required=True)
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--approval-sha256")
    parser.add_argument("--native-reuse-proof", type=Path)
    parser.add_argument("--native-reuse-proof-sha256")
    parser.add_argument("--source-repository", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    try:
        result = prepare(
            source_activation=args.source_activation,
            target_release_id=args.target_release_id,
            native_artifact_manifest=args.native_artifact_manifest,
            native_artifact_sha256=args.native_artifact_sha256,
            output_dir=args.output_dir,
            approval_file=args.approval_file,
            approval_sha256=args.approval_sha256,
            native_reuse_proof=args.native_reuse_proof,
            native_reuse_proof_sha256=args.native_reuse_proof_sha256,
            source_repository=args.source_repository,
        )
    except (PrepareError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
