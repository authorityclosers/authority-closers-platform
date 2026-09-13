#!/usr/bin/env python3
"""Verify one offline Sales Xray web image artifact without Docker or extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Never

SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY_DIGEST = re.compile(r"^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")
ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,80}$")
SUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^\r\n]+)$")

WEB_TAG_PREFIX = "ghcr.io/authorityclosers/ac-sales-xray-web:"
ARTIFACT_FILES = frozenset({"SHA256SUMS", "web-image.env", "web-image.json", "web-image.tar.gz"})
CHECKSUM_FILES = frozenset({"web-image.tar.gz", "web-image.json", "web-image.env"})
MAX_ARTIFACT_BYTES = 450_000_000
MAX_ARCHIVE_BYTES = 440_000_000
MAX_METADATA_BYTES = 256_000
MAX_ENV_BYTES = 16_384
MAX_SUMS_BYTES = 32_768
MAX_ARCHIVE_MEMBERS = 512
MAX_ARCHIVE_MEMBER_BYTES = 1_100_000_000
MAX_ARCHIVE_EXPANDED_BYTES = 2_000_000_000
MAX_INDEX_BYTES = 512_000
MAX_MANIFEST_BYTES = 1_000_000
MAX_CONFIG_BYTES = 8_000_000
MAX_LAYERS = 128


class VerificationError(ValueError):
    """Fixed verifier failure; artifact content never crosses the CLI boundary."""


def _fail() -> Never:
    raise VerificationError("sales_xray_web_artifact_invalid")


def _reject_constant(_: str) -> Never:
    _fail()


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _strict_json(raw: bytes, limit: int) -> Any:
    if len(raw) > limit:
        _fail()
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _fail()


def _require_keys(
    value: Any,
    keys: set[str],
    *,
    optional: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not keys.issubset(value)
        or not set(value).issubset(keys | set(optional))
    ):
        _fail()
    return value


def _string(value: Any, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        _fail()
    return value


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or HEX_SHA256.fullmatch(value) is None:
        _fail()
    return value


def _image_ref(value: Any) -> str:
    if not isinstance(value, str) or IMAGE_REF.fullmatch(value) is None:
        _fail()
    return value


def _regular_info(path: Path, *, maximum: int) -> os.stat_result:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            _fail()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_size != info.st_size
                or opened.st_size > maximum
            ):
                _fail()
        return info
    except (OSError, VerificationError):
        raise
    except Exception:
        _fail()


def _read_regular(path: Path, *, maximum: int) -> bytes:
    info = _regular_info(path, maximum=maximum)
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_size != info.st_size or opened.st_nlink != 1:
                _fail()
            data = stream.read(maximum + 1)
    except (OSError, VerificationError):
        raise
    if len(data) != info.st_size or len(data) > maximum:
        _fail()
    return data


def _file_sha256(path: Path) -> str:
    _regular_info(path, maximum=MAX_ARCHIVE_BYTES)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    except OSError:
        _fail()
    return digest.hexdigest()


def _artifact_dir(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        _fail()
    try:
        info = path.lstat()
    except OSError:
        _fail()
    if not stat.S_ISDIR(info.st_mode):
        _fail()
    try:
        entries = list(path.iterdir())
    except OSError:
        _fail()
    if {entry.name for entry in entries} != ARTIFACT_FILES or len(entries) != len(ARTIFACT_FILES):
        _fail()
    total = 0
    limits = {
        "SHA256SUMS": MAX_SUMS_BYTES,
        "web-image.env": MAX_ENV_BYTES,
        "web-image.json": MAX_METADATA_BYTES,
        "web-image.tar.gz": MAX_ARCHIVE_BYTES,
    }
    for entry in entries:
        total += _regular_info(entry, maximum=limits[entry.name]).st_size
    if total > MAX_ARTIFACT_BYTES:
        _fail()


def _parse_checksums(raw: bytes, files: dict[str, Path]) -> None:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        _fail()
    if not text.endswith("\n"):
        _fail()
    seen: dict[str, str] = {}
    for line in text.splitlines():
        match = SUM_LINE.fullmatch(line)
        if match is None:
            _fail()
        digest, name = match.groups()
        if name in seen or name not in CHECKSUM_FILES:
            _fail()
        seen[name] = digest
    if set(seen) != CHECKSUM_FILES:
        _fail()
    for name, digest in seen.items():
        if _file_sha256(files[name]) != digest:
            _fail()


def _parse_env(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        _fail()
    if not text.endswith("\n"):
        _fail()
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            _fail()
        key, value = line.split("=", 1)
        if ENV_KEY.fullmatch(key) is None or key in result or "\x00" in value:
            _fail()
        result[key] = value
    expected = {
        "AC_WEB_IMAGE",
        "AC_WEB_IMAGE_ID",
        "AC_WEB_IMAGE_TYPE",
        "AC_WEB_REGISTRY_DIGEST",
        "AC_WEB_TRANSPORT_FILE",
        "AC_WEB_TRANSPORT_MANIFEST_DIGEST",
        "AC_WEB_TRANSPORT_CONFIG_DIGEST",
        "AC_WEB_TRANSPORT_SHA256",
        "AC_WEB_RELEASE_ID",
    }
    if set(result) != expected:
        _fail()
    return result


def _archive_name(name: str) -> None:
    if (
        not name
        or len(name) > 512
        or "\\" in name
        or PurePosixPath(name).is_absolute()
        or ".." in PurePosixPath(name).parts
    ):
        _fail()


def _archive_members(archive_path: Path) -> tuple[dict[str, tarfile.TarInfo], int]:
    members: dict[str, tarfile.TarInfo] = {}
    expanded = 0
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for _ in range(MAX_ARCHIVE_MEMBERS + 1):
                member = archive.next()
                if member is None:
                    break
                _archive_name(member.name)
                if member.name in members:
                    _fail()
                if member.isdir():
                    if member.size != 0:
                        _fail()
                elif member.isfile() and member.type == tarfile.REGTYPE:
                    if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                        _fail()
                    expanded += member.size
                    if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                        _fail()
                else:
                    _fail()
                members[member.name] = member
            else:
                _fail()
    except (OSError, tarfile.TarError):
        _fail()
    if "index.json" not in members:
        _fail()
    return members, expanded


def _member_bytes(
    archive_path: Path,
    member: tarfile.TarInfo,
    *,
    maximum: int,
) -> bytes:
    if not member.isfile() or member.type != tarfile.REGTYPE or member.size > maximum:
        _fail()
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            stream = archive.extractfile(member)
            if stream is None:
                _fail()
            raw = stream.read(maximum + 1)
    except (OSError, tarfile.TarError):
        _fail()
    if len(raw) != member.size or len(raw) > maximum:
        _fail()
    return raw


def _descriptor_digest(value: Any) -> str:
    return _image_ref(value)


def _verify_transport(
    archive_path: Path,
    *,
    source_sha: str,
    runtime_ref: str,
    config_id: str,
) -> None:
    members, _expanded = _archive_members(archive_path)
    index = _strict_json(
        _member_bytes(archive_path, members["index.json"], maximum=MAX_INDEX_BYTES),
        MAX_INDEX_BYTES,
    )
    if not isinstance(index, dict) or index.get("schemaVersion") != 2:
        _fail()
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or not 0 < len(manifests) <= 16:
        _fail()
    expected_tag = WEB_TAG_PREFIX + source_sha
    matched: list[tuple[str, int]] = []
    for descriptor in manifests:
        if not isinstance(descriptor, dict):
            _fail()
        digest = _descriptor_digest(descriptor.get("digest"))
        size = descriptor.get("size")
        if type(size) is not int or not 0 < size <= MAX_ARCHIVE_MEMBER_BYTES:
            _fail()
        annotations = descriptor.get("annotations", {})
        if not isinstance(annotations, dict):
            _fail()
        if annotations.get("io.containerd.image.name") == expected_tag:
            matched.append((digest, size))
    if len(matched) != 1 or matched[0][0] != runtime_ref:
        _fail()
    manifest_digest, manifest_size = matched[0]
    manifest_path = "blobs/sha256/" + manifest_digest.removeprefix("sha256:")
    manifest_member = members.get(manifest_path)
    if manifest_member is None or manifest_member.size != manifest_size:
        _fail()
    manifest_raw = _member_bytes(archive_path, manifest_member, maximum=MAX_MANIFEST_BYTES)
    if "sha256:" + hashlib.sha256(manifest_raw).hexdigest() != manifest_digest:
        _fail()
    manifest = _strict_json(manifest_raw, MAX_MANIFEST_BYTES)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
        _fail()
    config = manifest.get("config")
    if not isinstance(config, dict):
        _fail()
    config_digest = _descriptor_digest(config.get("digest"))
    config_size = config.get("size")
    if config_digest != config_id or type(config_size) is not int or config_size <= 0:
        _fail()
    config_path = "blobs/sha256/" + config_digest.removeprefix("sha256:")
    config_member = members.get(config_path)
    if config_member is None or config_member.size != config_size:
        _fail()
    config_raw = _member_bytes(archive_path, config_member, maximum=MAX_CONFIG_BYTES)
    if "sha256:" + hashlib.sha256(config_raw).hexdigest() != config_digest:
        _fail()
    image_config = _strict_json(config_raw, MAX_CONFIG_BYTES)
    if not isinstance(image_config, dict):
        _fail()
    if image_config.get("architecture") != "amd64" or image_config.get("os") != "linux":
        _fail()
    runtime_config = image_config.get("config")
    if not isinstance(runtime_config, dict):
        _fail()
    if (
        runtime_config.get("User") != "node"
        or runtime_config.get("WorkingDir") != "/app"
        or runtime_config.get("Cmd") != ["node", "apps/sales-xray-web/server.js"]
    ):
        _fail()
    environment = runtime_config.get("Env")
    if not isinstance(environment, list) or any(
        not isinstance(value, str) for value in environment
    ):
        _fail()
    environment_values = dict(value.split("=", 1) for value in environment if "=" in value)
    if len(environment_values) != len(environment):
        _fail()
    for key, expected in {
        "AC_RELEASE_ID": source_sha,
        "HOSTNAME": "0.0.0.0",  # noqa: S104 - inspect baked runtime metadata only
        "NODE_ENV": "production",
        "NEXT_TELEMETRY_DISABLED": "1",
        "PORT": "3016",
    }.items():
        if environment_values.get(key) != expected:
            _fail()
    labels = runtime_config.get("Labels")
    if (
        not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != source_sha
    ):
        _fail()
    layers = manifest.get("layers")
    if not isinstance(layers, list) or len(layers) > MAX_LAYERS:
        _fail()
    for layer in layers:
        if not isinstance(layer, dict):
            _fail()
        layer_digest = _descriptor_digest(layer.get("digest"))
        layer_size = layer.get("size")
        if type(layer_size) is not int or not 0 <= layer_size <= MAX_ARCHIVE_MEMBER_BYTES:
            _fail()
        layer_member = members.get("blobs/sha256/" + layer_digest.removeprefix("sha256:"))
        if layer_member is None or layer_member.size != layer_size:
            _fail()


def _validate_metadata(
    raw: bytes,
    *,
    source_sha: str,
    archive_bytes: int,
    archive_sha: str,
) -> tuple[str, str, dict[str, Any]]:
    metadata = _strict_json(raw, MAX_METADATA_BYTES)
    top = _require_keys(
        metadata,
        {
            "schema",
            "source_commit",
            "context",
            "context_tree_id",
            "dockerfile",
            "dockerfile_sha256",
            "target",
            "platform",
            "image",
            "transport",
            "health",
            "registry_publish",
        },
    )
    if top["schema"] != "ac.sales-xray.web-image/1" or top["source_commit"] != source_sha:
        _fail()
    if (
        top["context"] != "."
        or SOURCE_SHA.fullmatch(_string(top["context_tree_id"])) is None
        or top["dockerfile"] != "infra/sales-xray-web/Dockerfile"
        or HEX_SHA256.fullmatch(_string(top["dockerfile_sha256"])) is None
        or top["target"] != "runtime"
    ):
        _fail()
    platform = _require_keys(top["platform"], {"os", "architecture"})
    if platform != {"os": "linux", "architecture": "amd64"}:
        _fail()
    image = _require_keys(
        top["image"],
        {"expected_runtime_ref", "image_id", "identity_type", "repository_digests", "release_id"},
    )
    runtime_ref = _image_ref(image["expected_runtime_ref"])
    config_id = _image_ref(image["image_id"])
    if image["identity_type"] != "oci_transport_manifest" or image["release_id"] != source_sha:
        _fail()
    repository_digests = image["repository_digests"]
    if not isinstance(repository_digests, list) or len(repository_digests) > 4:
        _fail()
    if any(
        not isinstance(value, str) or REPOSITORY_DIGEST.fullmatch(value) is None
        for value in repository_digests
    ):
        _fail()
    transport = _require_keys(
        top["transport"],
        {
            "format",
            "filename",
            "bytes",
            "sha256",
            "manifest_digest",
            "config_digest",
            "load_command",
            "inspect_command",
        },
        optional={"ci_bare_manifest_addressable"},
    )
    if (
        "ci_bare_manifest_addressable" in transport
        and type(transport["ci_bare_manifest_addressable"]) is not bool
    ):
        _fail()
    if (
        transport["format"] != "docker-save-tar-gzip"
        or transport["filename"] != "web-image.tar.gz"
        or type(transport["bytes"]) is not int
        or transport["bytes"] != archive_bytes
        or not 0 < transport["bytes"] <= MAX_ARCHIVE_BYTES
        or transport["sha256"] != archive_sha
        or transport["manifest_digest"] != runtime_ref
        or transport["config_digest"] != config_id
        or transport["load_command"] != "docker load --input web-image.tar.gz"
        or transport["inspect_command"] != "docker image inspect " + runtime_ref
    ):
        _fail()
    health = _require_keys(top["health"], {"path", "expected"})
    expected_health = _require_keys(health["expected"], {"status", "service", "release_id"})
    if health["path"] != "/health" or expected_health != {
        "status": "ok",
        "service": "sales-xray-web",
        "release_id": source_sha,
    }:
        _fail()
    registry = _require_keys(top["registry_publish"], {"performed", "reason", "repository_digest"})
    registry_digest = registry["repository_digest"]
    if registry["performed"] is not False:
        _fail()
    _string(registry["reason"], maximum=512)
    if not isinstance(registry["reason"], str):
        _fail()
    if registry_digest != "none" and (
        not isinstance(registry_digest, str) or REPOSITORY_DIGEST.fullmatch(registry_digest) is None
    ):
        _fail()
    if registry_digest != "none" and registry_digest not in repository_digests:
        _fail()
    return runtime_ref, config_id, {"registry_digest": registry_digest}


def verify(artifact_dir: Path, source_sha: str, metadata_sha256: str) -> dict[str, str]:
    if SOURCE_SHA.fullmatch(source_sha) is None or HEX_SHA256.fullmatch(metadata_sha256) is None:
        _fail()
    _artifact_dir(artifact_dir)
    files = {name: artifact_dir / name for name in ARTIFACT_FILES}
    metadata_raw = _read_regular(files["web-image.json"], maximum=MAX_METADATA_BYTES)
    if hashlib.sha256(metadata_raw).hexdigest() != metadata_sha256:
        _fail()
    env = _parse_env(_read_regular(files["web-image.env"], maximum=MAX_ENV_BYTES))
    archive_info = _regular_info(files["web-image.tar.gz"], maximum=MAX_ARCHIVE_BYTES)
    archive_sha = _file_sha256(files["web-image.tar.gz"])
    runtime_ref, config_id, metadata_details = _validate_metadata(
        metadata_raw,
        source_sha=source_sha,
        archive_bytes=archive_info.st_size,
        archive_sha=archive_sha,
    )
    if (
        env["AC_WEB_IMAGE"] != runtime_ref
        or env["AC_WEB_IMAGE_ID"] != config_id
        or env["AC_WEB_IMAGE_TYPE"] != "oci_transport_manifest"
        or env["AC_WEB_TRANSPORT_FILE"] != "web-image.tar.gz"
        or env["AC_WEB_TRANSPORT_MANIFEST_DIGEST"] != runtime_ref
        or env["AC_WEB_TRANSPORT_CONFIG_DIGEST"] != config_id
        or env["AC_WEB_TRANSPORT_SHA256"] != archive_sha
        or env["AC_WEB_RELEASE_ID"] != source_sha
        or env["AC_WEB_REGISTRY_DIGEST"] != metadata_details["registry_digest"]
    ):
        _fail()
    registry_digest = env["AC_WEB_REGISTRY_DIGEST"]
    if registry_digest != "none" and REPOSITORY_DIGEST.fullmatch(registry_digest) is None:
        _fail()
    _parse_checksums(_read_regular(files["SHA256SUMS"], maximum=MAX_SUMS_BYTES), files)
    _verify_transport(
        files["web-image.tar.gz"],
        source_sha=source_sha,
        runtime_ref=runtime_ref,
        config_id=config_id,
    )
    return {
        "verified_source": source_sha,
        "runtime_ref": runtime_ref,
        "config_id": config_id,
        "archive_sha": archive_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--source-sha40", required=True)
    parser.add_argument("--metadata-sha256", required=True)
    args = parser.parse_args()
    try:
        proof = verify(args.artifact_dir, args.source_sha40, args.metadata_sha256)
    except (OSError, tarfile.TarError, ValueError, TypeError, KeyError, IndexError):
        print("FAIL sales_xray_web_artifact_invalid", file=sys.stderr)
        return 1
    print(json.dumps(proof, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
