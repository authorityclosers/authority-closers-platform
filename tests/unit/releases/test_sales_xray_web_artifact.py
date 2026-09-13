from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
VERIFIER_PATH = ROOT / "infra" / "sales-xray-web" / "verify-artifact.py"
SPEC = importlib.util.spec_from_file_location("sales_xray_web_verify_artifact", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)

SOURCE = "0123456789abcdef0123456789abcdef01234567"
TAG = f"ghcr.io/authorityclosers/ac-sales-xray-web:{SOURCE}"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.mode = 0o644
    info.mtime = 0
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _make_transport(
    path: Path,
    *,
    traversal: bool = False,
    config_override: bytes | None = None,
) -> tuple[str, str]:
    config_payload = config_override or _json(
        {
            "architecture": "amd64",
            "config": {
                "Cmd": ["node", "apps/sales-xray-web/server.js"],
                "Env": [
                    "AC_RELEASE_ID=" + SOURCE,
                    "HOSTNAME=0.0.0.0",
                    "NODE_ENV=production",
                    "NEXT_TELEMETRY_DISABLED=1",
                    "PORT=3016",
                ],
                "Labels": {"org.opencontainers.image.revision": SOURCE},
                "User": "node",
                "WorkingDir": "/app",
            },
            "os": "linux",
        }
    )
    config_ref = "sha256:" + _sha256(config_payload)
    manifest_payload = _json(
        {
            "config": {"digest": config_ref, "size": len(config_payload)},
            "layers": [],
            "schemaVersion": 2,
        }
    )
    manifest_ref = "sha256:" + _sha256(manifest_payload)
    index_payload = _json(
        {
            "manifests": [
                {
                    "annotations": {"io.containerd.image.name": TAG},
                    "digest": manifest_ref,
                    "size": len(manifest_payload),
                }
            ],
            "schemaVersion": 2,
        }
    )
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        _write_member(archive, "index.json", index_payload)
        _write_member(archive, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}\n')
        _write_member(
            archive, "blobs/sha256/" + manifest_ref.removeprefix("sha256:"), manifest_payload
        )
        _write_member(archive, "blobs/sha256/" + config_ref.removeprefix("sha256:"), config_payload)
        if traversal:
            _write_member(archive, "../escaped", b"must never be extracted")
    return manifest_ref, config_ref


def _write_artifact(
    tmp_path: Path,
    *,
    traversal: bool = False,
    config_override: bytes | None = None,
) -> tuple[Path, str, str]:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    archive_path = artifact / "web-image.tar.gz"
    runtime_ref, config_id = _make_transport(
        archive_path, traversal=traversal, config_override=config_override
    )
    archive_sha = _sha256(archive_path.read_bytes())
    archive_bytes = archive_path.stat().st_size
    metadata: dict[str, Any] = {
        "context": ".",
        "context_tree_id": "a" * 40,
        "dockerfile": "infra/sales-xray-web/Dockerfile",
        "dockerfile_sha256": "b" * 64,
        "health": {
            "expected": {"release_id": SOURCE, "service": "sales-xray-web", "status": "ok"},
            "path": "/health",
        },
        "image": {
            "expected_runtime_ref": runtime_ref,
            "identity_type": "oci_transport_manifest",
            "image_id": config_id,
            "release_id": SOURCE,
            "repository_digests": [],
        },
        "platform": {"architecture": "amd64", "os": "linux"},
        "registry_publish": {
            "performed": False,
            "reason": "offline transport workflow does not push or require registry credentials",
            "repository_digest": "none",
        },
        "schema": "ac.sales-xray.web-image/1",
        "source_commit": SOURCE,
        "target": "runtime",
        "transport": {
            "bytes": archive_bytes,
            "ci_bare_manifest_addressable": False,
            "config_digest": config_id,
            "filename": "web-image.tar.gz",
            "format": "docker-save-tar-gzip",
            "inspect_command": "docker image inspect " + runtime_ref,
            "load_command": "docker load --input web-image.tar.gz",
            "manifest_digest": runtime_ref,
            "sha256": archive_sha,
        },
    }
    metadata_path = artifact / "web-image.json"
    metadata_raw = _json(metadata)
    metadata_path.write_bytes(metadata_raw)
    env = "".join(
        [
            f"AC_WEB_IMAGE={runtime_ref}\n",
            f"AC_WEB_IMAGE_ID={config_id}\n",
            "AC_WEB_IMAGE_TYPE=oci_transport_manifest\n",
            "AC_WEB_REGISTRY_DIGEST=none\n",
            "AC_WEB_TRANSPORT_FILE=web-image.tar.gz\n",
            f"AC_WEB_TRANSPORT_MANIFEST_DIGEST={runtime_ref}\n",
            f"AC_WEB_TRANSPORT_CONFIG_DIGEST={config_id}\n",
            f"AC_WEB_TRANSPORT_SHA256={archive_sha}\n",
            f"AC_WEB_RELEASE_ID={SOURCE}\n",
        ]
    )
    (artifact / "web-image.env").write_text(env, encoding="ascii")
    checksums = "".join(
        f"{_sha256((artifact / name).read_bytes())}  {name}\n"
        for name in ("web-image.tar.gz", "web-image.json", "web-image.env")
    )
    (artifact / "SHA256SUMS").write_text(checksums, encoding="ascii")
    return artifact, runtime_ref, config_id


def _run_cli(
    artifact: Path, source: str = SOURCE, metadata_sha: str | None = None
) -> subprocess.CompletedProcess[str]:
    metadata_sha = metadata_sha or _sha256((artifact / "web-image.json").read_bytes())
    return subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--artifact-dir",
            str(artifact),
            "--source-sha40",
            source,
            "--metadata-sha256",
            metadata_sha,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_accepts_synthetic_oci_transport_and_returns_small_proof(tmp_path: Path) -> None:
    artifact, runtime_ref, config_id = _write_artifact(tmp_path)

    result = _run_cli(artifact)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "archive_sha": _sha256((artifact / "web-image.tar.gz").read_bytes()),
        "config_id": config_id,
        "runtime_ref": runtime_ref,
        "verified_source": SOURCE,
    }


def test_rejects_wrong_source_and_metadata_digest(tmp_path: Path) -> None:
    artifact, _runtime_ref, _config_id = _write_artifact(tmp_path)

    assert _run_cli(artifact, source="f" * 40).returncode != 0
    metadata = artifact / "web-image.json"
    metadata.write_bytes(metadata.read_bytes().replace(b'"target":"runtime"', b'"target":"wrong"'))
    assert _run_cli(artifact).returncode != 0


def test_rejects_archive_traversal_without_extracting(tmp_path: Path) -> None:
    artifact, _runtime_ref, _config_id = _write_artifact(tmp_path, traversal=True)

    result = _run_cli(artifact)

    assert result.returncode != 0
    assert not (tmp_path / "escaped").exists()


def test_rejects_metadata_symlink(tmp_path: Path) -> None:
    artifact, _runtime_ref, _config_id = _write_artifact(tmp_path)
    target = tmp_path / "metadata-target"
    target.write_bytes((artifact / "web-image.json").read_bytes())
    metadata = artifact / "web-image.json"
    metadata.unlink()
    try:
        metadata.symlink_to(target)
    except OSError:
        pytest.skip("this host does not permit an unprivileged symlink fixture")

    assert _run_cli(artifact).returncode != 0


def test_rejects_unbounded_metadata_even_when_external_hash_matches(tmp_path: Path) -> None:
    artifact, _runtime_ref, _config_id = _write_artifact(tmp_path)
    metadata = artifact / "web-image.json"
    metadata.write_bytes(b"{" + b" " * verifier.MAX_METADATA_BYTES + b"}")

    assert _run_cli(artifact, metadata_sha=_sha256(metadata.read_bytes())).returncode != 0


def test_rejects_manifest_config_binding_mismatch(tmp_path: Path) -> None:
    artifact, _runtime_ref, config_id = _write_artifact(tmp_path)
    metadata = json.loads((artifact / "web-image.json").read_text(encoding="utf-8"))
    metadata["image"]["image_id"] = "sha256:" + "c" * 64
    metadata["transport"]["config_digest"] = metadata["image"]["image_id"]
    metadata["transport"]["inspect_command"] = (
        "docker image inspect " + metadata["image"]["expected_runtime_ref"]
    )
    metadata_raw = _json(metadata)
    (artifact / "web-image.json").write_bytes(metadata_raw)
    env_path = artifact / "web-image.env"
    env_path.write_text(
        env_path.read_text(encoding="ascii")
        .replace(f"AC_WEB_IMAGE_ID={config_id}", f"AC_WEB_IMAGE_ID={metadata['image']['image_id']}")
        .replace(
            f"AC_WEB_TRANSPORT_CONFIG_DIGEST={config_id}",
            f"AC_WEB_TRANSPORT_CONFIG_DIGEST={metadata['image']['image_id']}",
        ),
        encoding="ascii",
    )
    (artifact / "SHA256SUMS").write_text(
        "".join(
            f"{_sha256((artifact / name).read_bytes())}  {name}\n"
            for name in ("web-image.tar.gz", "web-image.json", "web-image.env")
        ),
        encoding="ascii",
    )

    result = _run_cli(artifact, metadata_sha=_sha256(metadata_raw))

    assert result.returncode != 0
    assert config_id != metadata["image"]["image_id"]


def test_rejects_hardlinked_artifact_file(tmp_path: Path) -> None:
    artifact, _runtime_ref, _config_id = _write_artifact(tmp_path)
    hardlink = tmp_path / "metadata-hardlink"
    try:
        os.link(artifact / "web-image.json", hardlink)
    except OSError:
        pytest.skip("this host does not permit an unprivileged hardlink fixture")

    assert _run_cli(artifact).returncode != 0


def test_rejects_untrusted_env_values_without_shell_execution(tmp_path: Path) -> None:
    artifact, _runtime_ref, _config_id = _write_artifact(tmp_path)
    env_path = artifact / "web-image.env"
    marker = tmp_path / "shell-executed"
    env_path.write_text(
        env_path.read_text(encoding="ascii").replace(
            "AC_WEB_REGISTRY_DIGEST=none", f"AC_WEB_REGISTRY_DIGEST=$(touch {marker})"
        ),
        encoding="ascii",
    )

    assert _run_cli(artifact).returncode != 0
    assert not marker.exists()
