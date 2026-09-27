from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "native_artifact_compatibility",
    ROOT / "infra/application/scripts/native_artifact_compatibility.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True).encode()


def git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - isolated test repository; no shell
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()


class Bundle:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet")
        git(self.repo, "config", "user.name", "Synthetic test")
        git(self.repo, "config", "user.email", "synthetic@example.invalid")
        git(self.repo, "config", "core.autocrlf", "false")
        self.files = {}
        for name in MODULE.INPUT_FILES:
            raw = (
                (ROOT / name).read_bytes()
                if name == MODULE.DOCKERFILE or name in MODULE.HELPER_RECIPES
                else ("fixture: " + name + "\n").encode()
            )
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.files[name] = raw
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "Native baseline")
        self.source = git(self.repo, "rev-parse", "HEAD")
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        (self.repo / "ui.txt").write_text("Unrelated UI change", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "API and UI followup")
        self.target = git(self.repo, "rev-parse", "HEAD")
        helper_buffer = io.BytesIO()
        with tarfile.open(fileobj=helper_buffer, mode="w:gz") as tar:
            for name in MODULE.HELPER_FILES:
                info = tarfile.TarInfo(name)
                info.size = len(self.files[name])
                tar.addfile(info, io.BytesIO(self.files[name]))
        helper = helper_buffer.getvalue()
        image = b"Synthetic transport; does not prove a Docker image runs."
        self.native = {
            "schema": "ac.sales-xray.native-image/1",
            "dockerfile": MODULE.DOCKERFILE,
            "target": "runtime",
            "platform": {"os": "linux", "architecture": "amd64"},
            "doctor": {"ffmpeg": True, "ffprobe": True, "provider_calls": False},
            "source_commit": self.source,
            "context": ".",
            "context_tree_id": tree,
            "dockerfile_sha256": digest(self.files[MODULE.DOCKERFILE]),
            "native_source_sha256": digest(self.files["native/audioatlas/atlas_dsp.cpp"]),
            "image": {
                "identity_type": "oci_transport_manifest",
                "expected_runtime_ref": "sha256:" + "a" * 64,
                "image_id": "sha256:" + "b" * 64,
            },
            "transport": {
                "manifest_digest": "sha256:" + "a" * 64,
                "config_digest": "sha256:" + "b" * 64,
                "filename": "native-image.tar.gz",
                "bytes": len(image),
                "sha256": digest(image),
            },
            "helper_source": {
                "entrypoint": "scripts/native_runtime_helper.py",
                "pythonpath": "packages/python",
                "filename": "native-helper.tar.gz",
                "bytes": len(helper),
                "sha256": digest(helper),
                "files": list(MODULE.HELPER_FILES),
            },
        }
        self.payload = {
            "native-image.json": encoded(self.native),
            "native-image.env": b"SYNTHETIC_TEST=true\n",
            "native-image.tar.gz": image,
            "native-helper.tar.gz": helper,
            "native-helper-files.sha256": self.sums(
                {n: self.files[n] for n in MODULE.HELPER_FILES}
            ),
        }
        self.artifact = {
            "id": 2,
            "name": "ac-sales-xray-native-" + self.source,
            "workflow_run": {
                "id": 1,
                "head_sha": self.source,
                "repository_id": 3,
                "head_repository_id": 3,
            },
        }
        self.run = {
            "id": 1,
            "repository": {"id": 3, "full_name": MODULE.REPOSITORY},
            "head_sha": self.source,
            "path": MODULE.WORKFLOW,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
        }
        self.archive = root / "archive.zip"
        self.manifest = root / "native-image.json"
        self.proof_path = root / "proof.json"
        self.refresh()

    @staticmethod
    def sums(files: dict[str, bytes]) -> bytes:
        return "".join(f"{digest(raw)}  {name}\n" for name, raw in files.items()).encode()

    def refresh(self) -> None:
        self.payload["native-image.json"] = encoded(self.native)
        self.manifest.write_bytes(self.payload["native-image.json"])
        with zipfile.ZipFile(self.archive, "w") as bundle:
            for name, raw in self.payload.items():
                bundle.writestr(name, raw)
            bundle.writestr("SHA256SUMS", self.sums(self.payload))
        self.artifact.update(
            size_in_bytes=self.archive.stat().st_size,
            digest="sha256:" + digest(self.archive.read_bytes()),
        )
        artifact_path, run_path = self.root / "artifact.json", self.root / "run.json"
        artifact_path.write_bytes(encoded(self.artifact))
        run_path.write_bytes(encoded(self.run))
        self.proof = {
            "schema": "ac.sales-xray.native-reuse-input/1",
            "repository": MODULE.REPOSITORY,
            "native_source_commit": self.source,
            "target_release_id": self.target,
            "artifact_metadata": {
                "path": str(artifact_path),
                "sha256": digest(artifact_path.read_bytes()),
            },
            "workflow_run": {"path": str(run_path), "sha256": digest(run_path.read_bytes())},
            "archive_path": str(self.archive),
        }
        self.proof_path.write_bytes(encoded(self.proof))

    def verify(self):
        return MODULE.verify_reuse(
            repository_root=self.repo,
            proof_path=self.proof_path,
            proof_sha256=digest(self.proof_path.read_bytes()),
            native_manifest=self.manifest,
            native_manifest_sha256=digest(self.manifest.read_bytes()),
            target_release=self.target,
        )


def test_reuse_proves_committed_inputs_without_relabeling_artifact(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    original = bundle.manifest.read_bytes()
    # Dirty checkout bytes cannot be mistaken for either committed version.
    (bundle.repo / "native/audioatlas/atlas_dsp.cpp").write_text("dirty", encoding="utf-8")
    result = bundle.verify()
    assert result["native_source_commit"] == bundle.source
    assert result["target_release_id"] == bundle.target
    assert result["native_context_tree"] != result["target_context_tree"]
    assert len(result["inputs"]) == len(MODULE.INPUT_FILES)
    assert result["activation_performed"] is False
    assert bundle.manifest.read_bytes() == original


@pytest.mark.parametrize("name", MODULE.INPUT_FILES)
def test_each_runtime_recipe_or_helper_change_requires_new_native_artifact(
    tmp_path: Path, name: str
) -> None:
    bundle = Bundle(tmp_path)
    (bundle.repo / name).write_bytes(bundle.files[name] + b"changed\n")
    git(bundle.repo, "add", ".")
    git(bundle.repo, "commit", "--quiet", "-m", "Changed native dependency")
    bundle.target = git(bundle.repo, "rev-parse", "HEAD")
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_inputs_changed"):
        bundle.verify()


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "f" * 40),
        ("conclusion", "failure"),
        ("status", "in_progress"),
        ("event", "pull_request"),
        ("path", ".github/workflows/unrelated.yml"),
        ("repository", {"id": 4, "full_name": "another/repository"}),
    ],
)
def test_original_ci_must_be_successful_and_bound(tmp_path: Path, field: str, value) -> None:
    bundle = Bundle(tmp_path)
    bundle.run[field] = value
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_ci_run_invalid"):
        bundle.verify()


def test_helper_bytes_must_equal_the_original_git_source_even_with_matching_checksums(
    tmp_path: Path,
) -> None:
    bundle = Bundle(tmp_path)
    contents = io.BytesIO()
    changed = dict(bundle.files)
    changed[MODULE.HELPER_FILES[0]] += b"modified helper\n"
    with tarfile.open(fileobj=contents, mode="w:gz") as tar:
        for name in MODULE.HELPER_FILES:
            info = tarfile.TarInfo(name)
            info.size = len(changed[name])
            tar.addfile(info, io.BytesIO(changed[name]))
    raw = contents.getvalue()
    bundle.payload["native-helper.tar.gz"] = raw
    bundle.payload["native-helper-files.sha256"] = bundle.sums(
        {n: changed[n] for n in MODULE.HELPER_FILES}
    )
    bundle.native["helper_source"].update(bytes=len(raw), sha256=digest(raw))
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="helper_source_mismatch"):
        bundle.verify()


def test_unbound_archive_and_source_tree_are_rejected(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    bundle.archive.write_bytes(bundle.archive.read_bytes() + b"changed")
    with pytest.raises(MODULE.NativeCompatibilityError, match="archive_size_invalid"):
        bundle.verify()
    bundle.native["context_tree_id"] = "0" * 40
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_context_tree_mismatch"):
        bundle.verify()


def test_pinned_metadata_cannot_change_after_review(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    (tmp_path / "run.json").write_bytes(encoded({**bundle.run, "id": 9876}))
    with pytest.raises(MODULE.NativeCompatibilityError, match="metadata_digest_mismatch"):
        bundle.verify()


def test_unexpected_zip_member_is_rejected_without_extraction(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    bundle.payload["../escape"] = b"must not be extracted"
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="archive_inventory_invalid"):
        bundle.verify()
    assert not (tmp_path.parent / "escape").exists()


def test_local_replace_refs_cannot_hide_changed_native_inputs(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    (bundle.repo / MODULE.HELPER_FILES[0]).write_text("changed", encoding="utf-8")
    git(bundle.repo, "add", ".")
    git(bundle.repo, "commit", "--quiet", "-m", "Different native helper")
    bundle.target = git(bundle.repo, "rev-parse", "HEAD")
    git(bundle.repo, "replace", bundle.target, bundle.source)
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_inputs_changed"):
        bundle.verify()


def test_mode_only_change_requires_new_native_review(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    git(bundle.repo, "update-index", "--chmod=+x", MODULE.HELPER_FILES[0])
    git(bundle.repo, "commit", "--quiet", "-m", "Changed helper mode only")
    bundle.target = git(bundle.repo, "rev-parse", "HEAD")
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_inputs_changed"):
        bundle.verify()


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "unrelated-artifact"),
        ("id", 991),
        ("head_sha", "f" * 40),
        ("repository_id", 4),
        ("head_repository_id", 4),
    ],
)
def test_artifact_cannot_substitute_another_run_source_or_fork(tmp_path, field, value):
    bundle = Bundle(tmp_path)
    if field == "name":
        bundle.artifact[field] = value
    else:
        bundle.artifact["workflow_run"][field] = value
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_ci_artifact_binding_invalid"):
        bundle.verify()


def test_same_size_archive_tampering_is_refused_before_parsing(tmp_path):
    bundle = Bundle(tmp_path)
    raw = bytearray(bundle.archive.read_bytes())
    raw[100] ^= 1
    bundle.archive.write_bytes(raw)
    with pytest.raises(MODULE.NativeCompatibilityError, match="archive_digest_mismatch"):
        bundle.verify()


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_release_id", "f" * 40),
        ("repository", "unrelated/repository"),
        ("unexpected", "field"),
    ],
)
def test_reviewed_proof_is_bound_to_exact_scope(tmp_path, field, value):
    bundle = Bundle(tmp_path)
    bundle.proof[field] = value
    bundle.proof_path.write_bytes(encoded(bundle.proof))
    with pytest.raises(MODULE.NativeCompatibilityError, match="reuse_proof_(scope|fields)_invalid"):
        bundle.verify()


@pytest.mark.parametrize("corruption", ["truncated", "deflate"])
def test_corrupt_but_digest_bound_helper_returns_sanitized_failure(tmp_path, corruption):
    bundle = Bundle(tmp_path)
    raw = bundle.payload["native-helper.tar.gz"][:10]
    if corruption == "deflate":
        raw += b"\xff" * 16
    bundle.payload["native-helper.tar.gz"] = raw
    bundle.native["helper_source"].update(bytes=len(raw), sha256=digest(raw))
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_compatibility_input_invalid"):
        bundle.verify()


def test_unreviewed_helper_import_closure_is_refused(tmp_path):
    bundle = Bundle(tmp_path)
    name = "scripts/native_runtime_helper.py"
    raw = bundle.files[name] + b"\nimport ac_platform.outside_bundle\n"
    (bundle.repo / name).write_bytes(raw)
    git(bundle.repo, "add", ".")
    git(bundle.repo, "commit", "--quiet", "-m", "New unreviewed helper baseline")
    bundle.source = git(bundle.repo, "rev-parse", "HEAD")
    bundle.native["source_commit"] = bundle.source
    bundle.native["context_tree_id"] = git(bundle.repo, "rev-parse", "HEAD^{tree}")
    (bundle.repo / "ui.txt").write_text("Another API change", encoding="utf-8")
    git(bundle.repo, "add", ".")
    git(bundle.repo, "commit", "--quiet", "-m", "Later unrelated API")
    bundle.target = git(bundle.repo, "rev-parse", "HEAD")
    bundle.refresh()
    with pytest.raises(MODULE.NativeCompatibilityError, match="native_helper_recipe_not_reviewed"):
        bundle.verify()


def test_real_preparer_and_verifier_integrate_without_monkeypatching(tmp_path):
    bundle = Bundle(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "reuse_prepare_test_support",
        ROOT / "tests/unit/test_prepare_sales_xray_native_activation.py",
    )
    assert spec and spec.loader
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    source, original_bytes = support._write_source_activation(tmp_path)
    output = tmp_path / "activation-output"
    result = support._MODULE.prepare(
        source_activation=source,
        target_release_id=bundle.target,
        native_artifact_manifest=bundle.manifest,
        native_artifact_sha256=digest(bundle.manifest.read_bytes()),
        output_dir=output,
        native_reuse_proof=bundle.proof_path,
        native_reuse_proof_sha256=digest(bundle.proof_path.read_bytes()),
        source_repository=bundle.repo,
    )
    receipt = json.loads(Path(result["native_compatibility_receipt"]).read_bytes())
    assert receipt["native_source_commit"] == bundle.source
    assert receipt["target_release_id"] == bundle.target
    assert receipt["activation_sha256"] == digest(Path(result["activation"]).read_bytes())
    assert result["approval_replaced"] is False
    assert all(Path(path).read_bytes() == raw for path, raw in original_bytes.items())
    with pytest.raises(support._MODULE.PrepareError, match="unnecessary for an exact-source"):
        support._MODULE.prepare(
            source_activation=source,
            target_release_id=bundle.source,
            native_artifact_manifest=bundle.manifest,
            native_artifact_sha256=digest(bundle.manifest.read_bytes()),
            output_dir=tmp_path / "unnecessary-proof",
            native_reuse_proof=bundle.proof_path,
            native_reuse_proof_sha256=digest(bundle.proof_path.read_bytes()),
            source_repository=bundle.repo,
        )
    assert not (tmp_path / "unnecessary-proof").exists()
