#!/usr/bin/env python3
"""Point Admin dev at an existing immutable admin-web image from a stored core release.

Admin dev (``admin-dev.authorityclosers.com`` behind the loopback edge
``127.0.0.1:3017``) runs the ``admin-web`` service of the root-owned dev compose
project ``acdev-xray``. AUT-285 pinned it by hand. This adapter moves it to the
admin-web image of a core release the release engine already stored and loaded
for staging. It never builds, pulls, tags or edits a container or the base
compose file, and touches no other service or environment.

    status   [--require-ancestor SHA ...] [--write-receipt]   read-only revision proof
    deploy   [--release SHA] [--require-ancestor SHA ...] [--apply]
    rollback [--apply]

Dry-run is the default: it runs every preflight and prints the exact plan.
``--apply`` writes the root-owned compose override, recreates only admin-web,
verifies image, revision label, health and the edge, and records the result. A
failed verification restores the previous override automatically. Output is one
JSON object of stable fields; command output is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

APPLICATION = Path("/srv/authority-closers/application")
MIRROR = Path("/var/lib/ac-release/mirror.git")
DEV_DIR = Path("/srv/authority-closers/development")
COMPOSE = DEV_DIR / "compose.yaml"
OVERRIDE = DEV_DIR / "compose.admin-web-release.yaml"
STATE = Path("/var/lib/ac-dev-admin-web")
RECEIPT = STATE / "deployed.json"
HISTORY = STATE / "history.jsonl"
PROJECT = "acdev-xray"
SERVICE = "admin-web"
CONTAINER = f"{PROJECT}-{SERVICE}-1"
IMAGE_REPOSITORY = "ghcr.io/authorityclosers/authority-closers-admin-web"
REVISION_LABEL = "org.opencontainers.image.revision"
EDGE = "http://127.0.0.1:3017"
HOST = "admin-dev.authorityclosers.com"
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
PATH_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
HEALTH_ATTEMPTS = 36
HEALTH_DELAY = 5.0


class DeployError(RuntimeError):
    """A fail-closed error carrying only a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - argv is built by this module.
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=PATH_ENV,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(argv, 127, "", "")


def require(ok: bool, code: str) -> None:
    if not ok:
        raise DeployError(code)


def compose_argv(*files: Path) -> list[str]:
    argv = ["docker", "compose", "-p", PROJECT, "--project-directory", str(DEV_DIR)]
    for file in files:
        argv += ["-f", str(file)]
    return argv


def override_text(sha: str) -> str:
    return (
        "# Written by deploy-dev-admin-web.py (AUT-970). Do not edit by hand;\n"
        "# every compose command for acdev-xray must pass this file after compose.yaml.\n"
        "services:\n"
        f"  {SERVICE}:\n"
        f"    image: {IMAGE_REPOSITORY}:{sha}\n"
        "    pull_policy: never\n"
    )


class Deployer:
    def __init__(self, runner=command, *, root: Path = Path("/"), sleep=time.sleep):
        self.run = runner
        self.root = root
        self.sleep = sleep

    def path(self, path: Path) -> Path:
        return self.root / path.relative_to("/")

    # Read-only inspection -------------------------------------------------

    def git_ancestor(self, older: str, newer: str) -> bool:
        argv = ["git", "--git-dir", str(MIRROR), "merge-base", "--is-ancestor", older, newer]
        return self.run(argv).returncode == 0

    def staging_release(self) -> str:
        link = self.path(APPLICATION / "current-staging")
        try:
            target = os.readlink(link)
        except OSError as error:
            raise DeployError("staging_release_unreadable") from error
        sha = Path(target).name
        require(SHA_RE.fullmatch(sha) is not None, "staging_release_invalid")
        return sha

    def release_admin_image(self, sha: str) -> str:
        release = self.path(APPLICATION / "releases" / sha)
        require(release.is_dir(), "release_not_stored")
        checked = self.run(
            ["sha256sum", "--check", "--quiet", str(release / "RELEASE-FILES.sha256")]
        )
        require(checked.returncode == 0, "release_checksum_failed")
        values: dict[str, str] = {}
        for line in (release / "release-images.env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
        require(values.get("AC_RELEASE_ID") == sha, "release_id_mismatch")
        image = values.get("AC_ADMIN_IMAGE", "")
        require(DIGEST_RE.fullmatch(image) is not None, "release_admin_image_invalid")
        return image

    def image(self, reference: str) -> dict[str, str] | None:
        fmt = '{{.Id}}|{{index .Config.Labels "' + REVISION_LABEL + '"}}'
        result = self.run(["docker", "image", "inspect", "--format", fmt, reference])
        if result.returncode != 0:
            return None
        image_id, _, revision = result.stdout.strip().partition("|")
        return {"id": image_id, "revision": revision}

    def container(self) -> dict[str, str] | None:
        fmt = (
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|"
            '{{.Image}}|{{.Config.Image}}|{{index .Config.Labels "' + REVISION_LABEL + '"}}'
        )
        result = self.run(["docker", "inspect", "--format", fmt, CONTAINER])
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split("|")
        if len(parts) != 5:
            return None
        keys = ("state", "health", "image", "reference", "revision")
        return dict(zip(keys, parts, strict=True))

    def http(self, path: str) -> tuple[str, str]:
        result = self.run(
            [
                "curl",
                "--silent",
                "--max-time",
                "15",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code} %{redirect_url}",
                "--header",
                f"Host: {HOST}",
                f"{EDGE}{path}",
            ]
        )
        code, _, redirect = result.stdout.strip().partition(" ")
        return code, redirect

    def edge_ok(self) -> bool:
        root = self.http("/")
        login = self.http("/login")
        return root == ("307", f"https://{HOST}/login") and login[0] == "200"

    def status(self, ancestors: list[str]) -> dict[str, Any]:
        live = self.container()
        require(live is not None, "container_missing")
        assert live is not None
        revision = live["revision"]
        verified = SHA_RE.fullmatch(revision) is not None
        contains = {sha: verified and self.git_ancestor(sha, revision) for sha in ancestors}
        receipt = self.read_receipt()
        return {
            "container": CONTAINER,
            "state": live["state"],
            "health": live["health"],
            "image": live["image"],
            "reference": live["reference"],
            "revision": revision,
            "edge_ok": self.edge_ok(),
            "contains": contains,
            "receipt_matches": bool(
                receipt
                and receipt.get("image") == live["image"]
                and receipt.get("revision") == revision
            ),
        }

    def read_receipt(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.path(RECEIPT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # Mutations ------------------------------------------------------------

    def write(self, path: Path, text: str, mode: int) -> None:
        target = self.path(path)
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}")
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, target)

    def restore_override(self, previous: str | None) -> None:
        if previous is None:
            self.path(OVERRIDE).unlink(missing_ok=True)
        else:
            self.write(OVERRIDE, previous, 0o644)

    def recreate(self, with_override: bool) -> bool:
        files = [COMPOSE, OVERRIDE] if with_override else [COMPOSE]
        argv = compose_argv(*files) + [
            "up",
            "--detach",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            SERVICE,
        ]
        return self.run(argv).returncode == 0

    def wait_serving(self, image: str, sha: str | None) -> bool:
        for _ in range(HEALTH_ATTEMPTS):
            live = self.container()
            if (
                live
                and live["state"] == "running"
                and live["health"] == "healthy"
                and live["image"] == image
                and (sha is None or live["revision"] == sha)
            ):
                return self.edge_ok()
            self.sleep(HEALTH_DELAY)
        return False

    def record(self, entry: dict[str, Any], receipt: dict[str, Any] | None) -> None:
        history = self.path(HISTORY)
        history.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        with history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        history.chmod(0o644)
        if receipt is not None:
            self.write(RECEIPT, json.dumps(receipt, indent=2, sort_keys=True) + "\n", 0o644)

    def receipt(self, live: dict[str, str], ancestors: list[str], action: str) -> dict[str, Any]:
        return {
            "host": HOST,
            "container": CONTAINER,
            "image": live["image"],
            "revision": live["revision"],
            "contains": sorted(
                sha for sha in ancestors if self.git_ancestor(sha, live["revision"])
            ),
            "action": action,
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # Commands -------------------------------------------------------------

    def preflight(self, sha: str, ancestors: list[str]) -> dict[str, Any]:
        require(SHA_RE.fullmatch(sha) is not None, "release_sha_invalid")
        require(all(SHA_RE.fullmatch(a) for a in ancestors), "ancestor_sha_invalid")
        require(self.path(COMPOSE).is_file(), "dev_compose_missing")
        require(self.git_ancestor(sha, "refs/heads/main"), "release_not_on_main")
        for ancestor in ancestors:
            require(self.git_ancestor(ancestor, sha), "release_missing_required_merge")
        image = self.release_admin_image(sha)
        tagged = self.image(f"{IMAGE_REPOSITORY}:{sha}")
        require(tagged is not None, "release_image_not_loaded")
        assert tagged is not None
        require(tagged["revision"] == sha, "release_image_revision_mismatch")
        manifest = self.image(image)
        require(manifest is not None and manifest["id"] == tagged["id"], "release_image_mismatch")
        live = self.container()
        require(live is not None, "container_missing")
        assert live is not None
        return {"image": image, "image_id": tagged["id"], "before": live}

    def deploy(self, sha: str | None, ancestors: list[str], *, apply: bool) -> dict[str, Any]:
        sha = sha or self.staging_release()
        plan = self.preflight(sha, ancestors)
        override = self.path(OVERRIDE)
        previous = override.read_text(encoding="utf-8") if override.is_file() else None
        validate = self.write_candidate(sha)
        result: dict[str, Any] = {
            "action": "deploy",
            "release": sha,
            "image": plan["image"],
            "before": plan["before"],
            "override": str(OVERRIDE),
            "compose": compose_argv(COMPOSE, OVERRIDE)
            + ["up", "--detach", "--no-deps", "--no-build", "--pull", "never", "--force-recreate"]
            + [SERVICE],
            "applied": False,
        }
        require(validate, "compose_config_invalid")
        if not apply:
            return result
        self.write(OVERRIDE, override_text(sha), 0o644)
        if not (self.recreate(True) and self.wait_serving(plan["image_id"], sha)):
            self.restore_override(previous)
            restored = self.recreate(previous is not None) and self.wait_serving(
                plan["before"]["image"], None
            )
            self.record(
                {**result, "applied": False, "rolled_back": restored, "previous": previous},
                None,
            )
            raise DeployError(
                "verify_failed_rolled_back" if restored else "verify_and_rollback_failed"
            )
        live = self.container()
        assert live is not None
        receipt = self.receipt(live, ancestors, "deploy")
        self.record(
            {**result, "applied": True, "previous": previous, "at": receipt["verified_at"]}, receipt
        )
        return {**result, "applied": True, "receipt": receipt}

    def write_candidate(self, sha: str) -> bool:
        """Validate the merged compose model with the candidate override, writing nothing live."""

        candidate = self.path(OVERRIDE).with_name(f".candidate-{os.getpid()}.yaml")
        candidate.write_text(override_text(sha), encoding="utf-8")
        try:
            result = self.run(compose_argv(COMPOSE, candidate) + ["config", "--format", "json"])
            if result.returncode != 0:
                return False
            model = json.loads(result.stdout or "{}")
            service = model.get("services", {}).get(SERVICE, {})
            return service.get("image") == f"{IMAGE_REPOSITORY}:{sha}" and "build" not in service
        except ValueError:
            return False
        finally:
            candidate.unlink(missing_ok=True)

    def rollback(self, *, apply: bool) -> dict[str, Any]:
        entries = []
        history = self.path(HISTORY)
        if history.is_file():
            entries = [json.loads(line) for line in history.read_text().splitlines() if line]
        deployed = [e for e in entries if e.get("action") == "deploy" and e.get("applied")]
        require(bool(deployed), "nothing_to_roll_back")
        last = deployed[-1]
        previous = last.get("previous")
        before = last["before"]
        result = {
            "action": "rollback",
            "from_release": last["release"],
            "to_image": before["image"],
            "to_revision": before["revision"],
            "override": "restore previous" if previous is not None else "remove",
            "applied": False,
        }
        if not apply:
            return result
        self.restore_override(previous)
        if not (self.recreate(previous is not None) and self.wait_serving(before["image"], None)):
            self.record({**result, "applied": False}, None)
            raise DeployError("rollback_verify_failed")
        live = self.container()
        assert live is not None
        receipt = self.receipt(live, [], "rollback")
        self.record({**result, "applied": True, "at": receipt["verified_at"]}, receipt)
        return {**result, "applied": True, "receipt": receipt}


def main(argv: list[str] | None = None, deployer: Deployer | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    status = sub.add_parser("status")
    status.add_argument("--require-ancestor", action="append", default=[])
    status.add_argument("--write-receipt", action="store_true")
    deploy = sub.add_parser("deploy")
    deploy.add_argument("--release")
    deploy.add_argument("--require-ancestor", action="append", default=[])
    deploy.add_argument("--apply", action="store_true")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    host = deployer is None
    deployer = deployer or Deployer()
    try:
        require(not host or os.geteuid() == 0, "root_required")
        if args.verb == "status":
            result = deployer.status(args.require_ancestor)
            if args.write_receipt:
                live = deployer.container()
                assert live is not None
                require(result["edge_ok"] and live["health"] == "healthy", "not_serving")
                receipt = deployer.receipt(live, args.require_ancestor, "status")
                deployer.write(RECEIPT, json.dumps(receipt, indent=2, sort_keys=True) + "\n", 0o644)
                result["receipt"] = receipt
        elif args.verb == "deploy":
            result = deployer.deploy(args.release, args.require_ancestor, apply=args.apply)
        else:
            result = deployer.rollback(apply=args.apply)
    except DeployError as error:
        print(json.dumps({"ok": False, "error": error.code}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
