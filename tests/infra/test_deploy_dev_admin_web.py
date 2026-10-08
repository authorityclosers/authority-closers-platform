"""Admin dev image adapter contract; a fake Docker/git host under tmp_path, never the server."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/deploy-dev-admin-web.py"
spec = importlib.util.spec_from_file_location("deploy_dev_admin_web", SCRIPT)
deploy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = deploy
assert spec.loader
spec.loader.exec_module(deploy)

OLD = "14c5311d8489c96c22d0ce098c45d930125432ba"
NEW = "ee819d0f5b18779c05b5661b06e76f27cabb2ca1"
MERGE = "1daeb17431a83a1330e9ec5f2362c29d3bb39c30"
OLD_ID = "sha256:" + "8" * 64
NEW_ID = "sha256:" + "e" * 64
TAG = f"{deploy.IMAGE_REPOSITORY}:{NEW}"


class FakeHost:
    def __init__(self, root: Path, *, healthy: bool = True):
        self.root = root
        self.calls: list[list[str]] = []
        self.ancestry = {(NEW, "refs/heads/main"), (OLD, "refs/heads/main"), (MERGE, NEW)}
        self.images = {TAG: (NEW_ID, NEW), NEW_ID: (NEW_ID, NEW), OLD_ID: (OLD_ID, OLD)}
        self.live = (OLD_ID, OLD)
        self.healthy = healthy
        self.lightweight_healthcheck = False
        app = root / "srv/authority-closers/application"
        release = app / "releases" / NEW
        release.mkdir(parents=True)
        (release / "release-images.env").write_text(
            f"AC_RELEASE_ID={NEW}\nAC_ADMIN_IMAGE={NEW_ID}\nAC_API_IMAGE=sha256:{'a' * 64}\n"
        )
        digest = hashlib.sha256((release / "release-images.env").read_bytes()).hexdigest()
        # Relative names, as the installer writes them.
        (release / "RELEASE-FILES.sha256").write_text(f"{digest}  ./release-images.env\n")
        (app / "current-staging").symlink_to(release)
        dev = root / "srv/authority-closers/development"
        dev.mkdir(parents=True)
        (dev / "compose.yaml").write_text("services: {}\n")

    def at(self, path: Path) -> Path:
        return path if str(path).startswith(str(self.root)) else self.root / path.relative_to("/")

    def __call__(self, argv, cwd=None):
        self.calls.append(argv)
        done = lambda code=0, out="": subprocess.CompletedProcess(argv, code, out, "")  # noqa: E731
        if argv[:2] == ["git", "--git-dir"]:
            return done(0 if (argv[5], argv[6]) in self.ancestry else 1)
        if argv[0] == "sha256sum":
            # The real tool: the manifest only verifies from inside the release dir.
            assert argv[-1] == "RELEASE-FILES.sha256" and cwd is not None
            return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603
        if argv[:3] == ["docker", "image", "inspect"]:
            found = self.images.get(argv[-1])
            label = "1" if self.lightweight_healthcheck else ""
            return done(0, f"{found[0]}|{found[1]}|{label}\n") if found else done(1)
        if argv[:2] == ["docker", "inspect"]:
            health = "healthy" if self.healthy else "unhealthy"
            image, revision = self.live
            return done(0, f"running|{health}|{image}|ref|{revision}\n")
        if argv[:2] == ["docker", "compose"]:
            files = [Path(argv[i + 1]) for i, a in enumerate(argv) if a == "-f"]
            override = [f for f in files if f.name != "compose.yaml"]
            if "config" in argv:
                text = self.at(override[0]).read_text() if override else ""
                image = text.split("image: ")[1].split("\n")[0] if "image: " in text else None
                return done(0, json.dumps({"services": {"admin-web": {"image": image}}}))
            if "up" in argv:
                if override and self.at(override[0]).is_file():
                    text = self.at(override[0]).read_text()
                    tag = text.split("image: ")[1].split("\n")[0]
                    self.live = self.images[tag]
                else:
                    self.live = (OLD_ID, OLD)
                return done()
        if argv[0] == "curl":
            return done(
                0, "200 " if argv[-1].endswith("/login") else f"307 https://{deploy.HOST}/login"
            )
        raise AssertionError(argv)


@pytest.fixture
def host(tmp_path):
    return FakeHost(tmp_path)


def run(host, *argv):
    deployer = deploy.Deployer(host, root=host.root, sleep=lambda _: None)
    lines: list[str] = []
    deploy.print = lines.append  # module global shadows the builtin for main()
    try:
        code = deploy.main(list(argv), deployer)
    finally:
        del deploy.print
    return code, json.loads(lines[-1])


def mutations(host):
    return [c for c in host.calls if c[:2] == ["docker", "compose"] and "up" in c]


def test_dry_run_plans_staging_release_without_changing_anything(host):
    code, out = run(host, "deploy", "--require-ancestor", MERGE)
    assert code == 0 and out["release"] == NEW and out["applied"] is False
    assert out["image"] == NEW_ID and out["before"]["revision"] == OLD
    assert "--no-build" in out["compose"] and out["compose"][-1] == "admin-web"
    assert not mutations(host)
    assert not (host.root / deploy.OVERRIDE.relative_to("/")).exists()
    assert not list((host.root / deploy.DEV_DIR.relative_to("/")).glob(".candidate-*"))


def test_apply_serves_release_image_and_writes_receipt(host):
    code, out = run(host, "deploy", "--require-ancestor", MERGE, "--apply")
    assert code == 0 and out["applied"] is True
    override = (host.root / deploy.OVERRIDE.relative_to("/")).read_text()
    assert f"image: {TAG}" in override and "pull_policy: never" in override
    receipt = json.loads((host.root / deploy.RECEIPT.relative_to("/")).read_text())
    assert receipt["revision"] == NEW and receipt["image"] == NEW_ID
    assert receipt["contains"] == [MERGE] and receipt["host"] == deploy.HOST
    up = mutations(host)[0]
    assert up[-1] == "admin-web" and "--no-deps" in up and up[-4:-2] == ["--pull", "never"]
    assert not any(c[:2] == ["docker", "pull"] or "build" in c[:3] for c in host.calls)
    assert "healthcheck:" not in override  # Older images keep their existing probe.


def test_new_image_adopts_lightweight_probe_and_rollback_restores_previous_override(host):
    previous = f"services:\n  admin-web:\n    image: {OLD_ID}\n"
    host.at(deploy.OVERRIDE).write_text(previous)
    host.lightweight_healthcheck = True
    code, out = run(host, "deploy", "--require-ancestor", MERGE, "--apply")
    assert code == 0 and out["applied"] is True
    override = host.at(deploy.OVERRIDE).read_text()
    assert "/usr/local/bin/ac-http-healthcheck, http://127.0.0.1:3001/healthz" in override
    assert "interval: 30s" in override and "start_period: 30s" in override
    code, out = run(host, "rollback", "--apply")
    assert code == 0 and out["applied"] is True
    assert host.at(deploy.OVERRIDE).read_text() == previous


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda h: h.ancestry.discard((MERGE, NEW)), "release_missing_required_merge"),
        (lambda h: h.ancestry.discard((NEW, "refs/heads/main")), "release_not_on_main"),
        (lambda h: h.images.pop(TAG), "release_image_not_loaded"),
        (lambda h: h.images.__setitem__(TAG, (NEW_ID, OLD)), "release_image_revision_mismatch"),
        (lambda h: h.images.__setitem__(NEW_ID, (OLD_ID, NEW)), "release_image_mismatch"),
    ],
)
def test_preflight_refuses_before_any_change(host, change, error):
    change(host)
    code, out = run(host, "deploy", "--require-ancestor", MERGE, "--apply")
    assert (code, out) == (1, {"ok": False, "error": error})
    assert not mutations(host)


def test_release_must_match_its_manifest(host):
    code, out = run(host, "deploy", "--release", OLD, "--apply")
    assert (code, out["error"]) == (1, "release_not_stored")


def test_failed_verification_restores_previous_image(tmp_path):
    host = FakeHost(tmp_path, healthy=False)
    code, out = run(host, "deploy", "--apply")
    assert (code, out["error"]) == (1, "verify_and_rollback_failed")
    assert not (host.root / deploy.OVERRIDE.relative_to("/")).exists()
    assert host.live == (OLD_ID, OLD)
    history = (host.root / deploy.HISTORY.relative_to("/")).read_text().splitlines()
    assert json.loads(history[-1])["applied"] is False
    assert not (host.root / deploy.RECEIPT.relative_to("/")).exists()


def test_rollback_restores_previous_state(host):
    run(host, "deploy", "--apply")
    code, plan = run(host, "rollback")
    assert code == 0 and plan["to_revision"] == OLD and plan["override"] == "remove"
    assert host.live == (NEW_ID, NEW)
    code, out = run(host, "rollback", "--apply")
    assert code == 0 and out["applied"] is True and host.live == (OLD_ID, OLD)
    assert not (host.root / deploy.OVERRIDE.relative_to("/")).exists()
    receipt = json.loads((host.root / deploy.RECEIPT.relative_to("/")).read_text())
    assert receipt["revision"] == OLD and receipt["action"] == "rollback"


def test_status_is_read_only_and_proves_revision(host):
    code, out = run(host, "status", "--require-ancestor", MERGE)
    assert code == 0 and out["revision"] == OLD and out["contains"] == {MERGE: False}
    assert out["edge_ok"] is True and out["receipt_matches"] is False
    assert not mutations(host) and not (host.root / "var").exists()
    run(host, "deploy", "--require-ancestor", MERGE, "--apply")
    code, out = run(host, "status", "--require-ancestor", MERGE)
    assert out["contains"] == {MERGE: True} and out["receipt_matches"] is True


def test_tampered_release_files_refuse(host):
    release = host.root / "srv/authority-closers/application/releases" / NEW
    env = release / "release-images.env"
    env.write_text(env.read_text().replace(NEW_ID, OLD_ID))
    code, out = run(host, "deploy", "--apply")
    assert (code, out["error"]) == (1, "release_checksum_failed")
    assert not mutations(host)


def test_status_refuses_malformed_ancestor(host):
    code, out = run(host, "status", "--require-ancestor", "HEAD", "--write-receipt")
    assert (code, out["error"]) == (1, "ancestor_sha_invalid")
    assert not any(c[0] == "git" for c in host.calls)
    assert not (host.root / deploy.RECEIPT.relative_to("/")).exists()
