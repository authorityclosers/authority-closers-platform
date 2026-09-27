"""Offline proof for reusing one CI-built native artifact with a later API.

GitHub metadata is an operator-supplied, independently captured input, not a
network lookup or a signature. Its exact hashes must be pinned in the reviewed
proof. Nothing in this module grants deployment or provider-call authority.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import subprocess
import tarfile
import zipfile
import zlib
from pathlib import Path
from typing import IO, Any, cast

REPOSITORY = "authorityclosers/authority-closers-platform"
WORKFLOW = ".github/workflows/sales-xray-native-image.yml"
DOCKERFILE = "infra/conversation-worker/Dockerfile"
# The complete COPY/dependency set below has been reviewed for this recipe.
# An unfamiliar recipe needs a fresh build or an explicit code review here.
RECIPE_SHA256 = "f35dc9842adff174efce5f26ee5e323e9a0d2169221f9708ea445d1f110c6658"
# The host runtime/helper import only stdlib and the packaged signal parser.
# The smoke harness has a reviewed optional full-app measurement import; its
# ImportError path explicitly reports upload_preflight_measured=False. Pin
# these recipes too: a changed import closure needs a new explicit review.
HELPER_RECIPES = {
    "packages/python/ac_platform/conversation_intelligence/native_runtime.py": (
        "c683c009cbf939021f2ca2abca370d269907d2a190c7432327fa1a5e4c55839a"
    ),
    "scripts/native_runtime_helper.py": (
        "96e4b198c19f3d34e18df234f206dc6848c0e7d49965ce46324ffdcd5982bd15"
    ),
    "scripts/test_hosted_native_linux.py": (
        "fd9bf391e5a1a98b90f2d00ea38130a9c4d9ee4ac243bfe722c5face3302cd1d"
    ),
}
HELPER_FILES = (
    "packages/python/ac_platform/__init__.py",
    "packages/python/ac_platform/conversation_intelligence/__init__.py",
    "packages/python/ac_platform/conversation_intelligence/native_runtime.py",
    "packages/python/ac_platform/conversation_intelligence/signals.py",
    "scripts/native_runtime_helper.py",
    "scripts/test_hosted_native_linux.py",
)
INPUT_FILES = tuple(
    sorted(
        set(HELPER_FILES)
        | {
            ".dockerignore",
            WORKFLOW,
            DOCKERFILE,
            "packages/python/ac_platform/conversation_intelligence/__main__.py",
            "native/audioatlas/atlas_dsp.cpp",
            "native/audioatlas/LICENSE",
            "native/audioatlas/source_provenance.json",
            "infra/release/validate-artifact-pool.py",
        }
    )
)
PAYLOAD = frozenset(
    {
        "SHA256SUMS",
        "native-image.json",
        "native-image.env",
        "native-image.tar.gz",
        "native-helper.tar.gz",
        "native-helper-files.sha256",
    }
)
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_ARCHIVE = 450_000_000


class NativeCompatibilityError(ValueError):
    """Content-free compatibility failure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise NativeCompatibilityError(code)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def parse(raw: bytes) -> dict[str, Any]:
    result = json.loads(raw, object_pairs_hook=_pairs)
    require(isinstance(result, dict), "json_object_required")
    return cast(dict[str, Any], result)


def stream_sha(stream: IO[bytes]) -> str:
    value = hashlib.sha256()
    while block := stream.read(1_048_576):
        value.update(block)
    return value.hexdigest()


def read(path: Path, limit: int = 1_000_000) -> bytes:
    require(path.is_absolute() and ".." not in path.parts, "absolute_input_required")
    require(not path.is_symlink() and path.is_file(), "regular_input_required")
    require(0 < path.stat().st_size <= limit, "input_size_invalid")
    raw = path.read_bytes()
    require(0 < len(raw) <= limit, "input_size_invalid")
    return raw


def _git(root: Path, *args: str) -> bytes:
    # Only fixed plumbing commands and validated full object IDs are used.
    result = subprocess.run(  # noqa: S603 - no shell; explicit Git plumbing arguments
        ["git", "--no-replace-objects", "-C", str(root), *args],  # noqa: S607
        capture_output=True,
        check=False,
        timeout=20,
    )
    require(result.returncode == 0, "git_object_unavailable")
    return result.stdout


def source_inputs(root: Path, source: str) -> tuple[str, dict[str, bytes]]:
    require(bool(SHA40.fullmatch(source)), "full_source_sha_required")
    require(
        _git(root, "rev-parse", "--verify", source + "^{commit}").strip().decode() == source,
        "source_commit_mismatch",
    )
    tree = _git(root, "rev-parse", source + "^{tree}").strip().decode()
    files: dict[str, bytes] = {}
    for name in INPUT_FILES:
        entry = _git(root, "ls-tree", "-z", source, "--", name)
        require(entry.count(b"\x00") == 1, "native_input_missing")
        metadata, actual = entry.rstrip(b"\x00").split(b"\t", 1)
        require(
            actual.decode() == name and metadata.split()[0] in {b"100644", b"100755"},
            "native_input_not_regular",
        )
        raw = _git(root, "show", source + ":" + name)
        require(len(raw) <= 2_000_000, "native_input_too_large")
        # File mode is part of compatibility even when blob contents match.
        files[name] = metadata.split()[0] + b"\x00" + raw
    return tree, files


def _pinned_json(proof: dict[str, Any], field: str) -> tuple[dict[str, Any], str]:
    binding = proof[field]
    raw = read(Path(binding["path"]))
    digest = sha(raw)
    require(digest == binding["sha256"], "metadata_digest_mismatch")
    return parse(raw), digest


def _checksums(raw: bytes, expected: set[str] | frozenset[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        require(match is not None, "checksum_format_invalid")
        assert match is not None
        digest, name = match.groups()
        require(name not in result and name in expected, "checksum_inventory_invalid")
        result[name] = digest
    require(set(result) == expected, "checksum_inventory_invalid")
    return result


def verify_reuse(
    *,
    repository_root: Path,
    proof_path: Path,
    proof_sha256: str,
    native_manifest: Path,
    native_manifest_sha256: str,
    target_release: str,
) -> dict[str, Any]:
    """Verify the complete retained CI bundle and unchanged Git-object inputs."""
    try:
        proof_raw = read(proof_path)
        require(sha(proof_raw) == proof_sha256, "reuse_proof_digest_mismatch")
        proof = parse(proof_raw)
        require(
            set(proof)
            == {
                "schema",
                "repository",
                "native_source_commit",
                "target_release_id",
                "artifact_metadata",
                "workflow_run",
                "archive_path",
            },
            "reuse_proof_fields_invalid",
        )
        require(
            proof["schema"] == "ac.sales-xray.native-reuse-input/1"
            and proof["repository"] == REPOSITORY
            and proof["target_release_id"] == target_release,
            "reuse_proof_scope_invalid",
        )
        native_raw = read(native_manifest)
        require(sha(native_raw) == native_manifest_sha256, "native_manifest_digest_mismatch")
        native = parse(native_raw)
        source = native["source_commit"]
        require(
            source == proof["native_source_commit"] and source != target_release,
            "native_source_binding_invalid",
        )
        source_tree, originals = source_inputs(repository_root, source)
        target_tree, targets = source_inputs(repository_root, target_release)
        require(
            native["context"] == "." and native["context_tree_id"] == source_tree,
            "native_context_tree_mismatch",
        )
        require(originals == targets, "native_inputs_changed")
        blobs = {name: raw.split(b"\x00", 1)[1] for name, raw in originals.items()}
        require(
            sha(blobs[DOCKERFILE]) == RECIPE_SHA256 == native["dockerfile_sha256"],
            "native_recipe_not_reviewed",
        )
        require(
            all(sha(blobs[name]) == digest for name, digest in HELPER_RECIPES.items()),
            "native_helper_recipe_not_reviewed",
        )
        require(
            sha(blobs["native/audioatlas/atlas_dsp.cpp"]) == native["native_source_sha256"],
            "native_kernel_digest_mismatch",
        )
        artifact, artifact_digest = _pinned_json(proof, "artifact_metadata")
        run, run_digest = _pinned_json(proof, "workflow_run")
        require(
            run["repository"]["full_name"] == REPOSITORY
            and run["head_sha"] == source
            and run["path"] == WORKFLOW
            and run["event"] == "workflow_dispatch"
            and run["status"] == "completed"
            and run["conclusion"] == "success",
            "native_ci_run_invalid",
        )
        require(
            artifact["name"] == "ac-sales-xray-native-" + source
            and artifact["workflow_run"]["id"] == run["id"]
            and artifact["workflow_run"]["head_sha"] == source
            and artifact["workflow_run"]["repository_id"] == run["repository"]["id"]
            and artifact["workflow_run"]["head_repository_id"] == run["repository"]["id"],
            "native_ci_artifact_binding_invalid",
        )
        archive_path = Path(proof["archive_path"])
        require(
            archive_path.is_absolute()
            and ".." not in archive_path.parts
            and archive_path.is_file()
            and not archive_path.is_symlink(),
            "archive_path_invalid",
        )
        require(
            0 < artifact["size_in_bytes"] == archive_path.stat().st_size <= MAX_ARCHIVE,
            "archive_size_invalid",
        )
        with archive_path.open("rb") as stream:
            archive_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            require(artifact["digest"] == "sha256:" + archive_digest, "archive_digest_mismatch")
            stream.seek(0)
            with zipfile.ZipFile(stream) as bundle:
                members = bundle.infolist()
                require(
                    len(members) == len(PAYLOAD) and {m.filename for m in members} == PAYLOAD,
                    "archive_inventory_invalid",
                )
                require(
                    sum(m.file_size for m in members) <= MAX_ARCHIVE
                    and all(
                        not m.flag_bits & 1
                        and not m.is_dir()
                        and not stat.S_ISLNK(m.external_attr >> 16)
                        for m in members
                    ),
                    "archive_member_invalid",
                )
                require(
                    all(
                        bundle.getinfo(name).file_size <= 1_000_000
                        for name in PAYLOAD
                        if not name.endswith(".tar.gz")
                    ),
                    "archive_metadata_too_large",
                )
                sums = _checksums(bundle.read("SHA256SUMS"), PAYLOAD - {"SHA256SUMS"})
                for name, digest in sums.items():
                    with bundle.open(name) as item:
                        require(
                            stream_sha(item) == digest,
                            "payload_digest_mismatch",
                        )
                require(bundle.read("native-image.json") == native_raw, "manifest_not_from_archive")
                transport = native["transport"]
                helper = native["helper_source"]
                for section, name in (
                    (transport, "native-image.tar.gz"),
                    (helper, "native-helper.tar.gz"),
                ):
                    require(
                        section["filename"] == name
                        and section["sha256"] == sums[name]
                        and section["bytes"] == bundle.getinfo(name).file_size,
                        "native_transport_binding_invalid",
                    )
                require(
                    len(helper["files"]) == len(HELPER_FILES)
                    and set(helper["files"]) == set(HELPER_FILES),
                    "helper_inventory_invalid",
                )
                require(
                    bundle.getinfo("native-helper.tar.gz").file_size <= 20_000_000,
                    "helper_archive_too_large",
                )
                helper_sums = _checksums(
                    bundle.read("native-helper-files.sha256"), set(HELPER_FILES)
                )
                with tarfile.open(
                    fileobj=io.BytesIO(bundle.read("native-helper.tar.gz")), mode="r:gz"
                ) as tar:
                    seen: set[str] = set()
                    for entry in tar:
                        require(
                            entry.name in HELPER_FILES and entry.name not in seen,
                            "helper_inventory_invalid",
                        )
                        seen.add(entry.name)
                        require(
                            entry.isfile() and 0 <= entry.size <= 2_000_000, "helper_entry_invalid"
                        )
                        tar_item = tar.extractfile(entry)
                        require(tar_item is not None, "helper_entry_invalid")
                        assert tar_item is not None
                        with tar_item:
                            raw = tar_item.read(2_000_001)
                        require(
                            raw == blobs[entry.name] and sha(raw) == helper_sums[entry.name],
                            "helper_source_mismatch",
                        )
                    require(seen == set(HELPER_FILES), "helper_inventory_invalid")
        return {
            "schema": "ac.sales-xray.native-compatibility/1",
            "native_source_commit": source,
            "target_release_id": target_release,
            "native_context_tree": source_tree,
            "target_context_tree": target_tree,
            "native_manifest_sha256": native_manifest_sha256,
            "image_ref": native["image"]["expected_runtime_ref"],
            "config_id": native["image"]["image_id"],
            "proof_sha256": proof_sha256,
            "artifact_metadata_sha256": artifact_digest,
            "workflow_run_sha256": run_digest,
            "github_archive_sha256": archive_digest,
            "artifact_id": artifact["id"],
            "run_id": run["id"],
            "inputs": [
                {
                    "path": n,
                    "mode": originals[n].split(b"\x00", 1)[0].decode(),
                    "sha256": sha(blobs[n]),
                    "bytes": len(blobs[n]),
                }
                for n in INPUT_FILES
            ],
            "provider_calls": 0,
            "activation_performed": False,
        }
    except NativeCompatibilityError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
        tarfile.TarError,
        EOFError,
        zlib.error,
    ) as exc:
        raise NativeCompatibilityError("native_compatibility_input_invalid") from exc
