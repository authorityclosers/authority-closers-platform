#!/usr/bin/env python3
"""Boot exact Linux Admin/Coach release images; no API, credentials or host ports.

Unit tests of this controller are not an artifact pass. A pass is emitted only
after both original image commands start and the in-container HTTP probes pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
CONTAINER = re.compile(r"[0-9a-f]{64}\Z")
OWNER_LABEL = "com.authorityclosers.release-runtime-proof"
REVISION_LABEL = "org.opencontainers.image.revision"
PROBE = Path(__file__).with_name("verify-release-operations-probe.mjs")


class GateError(RuntimeError):
    """Only fixed, credential-free errors may cross the CLI boundary."""


def docker_operation(arguments: list[str]) -> str:
    """Return a fixed diagnostic label without rendering Docker arguments."""

    prefix = tuple(arguments[:2])
    if prefix == ("context", "inspect"):
        return "local-context inspection"
    if arguments[:1] == ["info"]:
        return "engine inspection"
    if prefix == ("image", "inspect"):
        return "image inspection"
    if prefix == ("container", "ls"):
        return "proof-container lookup"
    if prefix == ("container", "inspect"):
        return "proof-container inspection"
    return {
        "create": "proof-container creation",
        "start": "proof-container startup",
        "exec": "runtime HTTP probe",
        "rm": "proof-container cleanup",
    }.get(arguments[0] if arguments else "", "command")


class Docker:
    def __init__(self) -> None:
        # Never inherit tokens, application credentials, DOCKER_HOST or a remote context.
        self.environment = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
        self.environment["LC_ALL"] = "C"

    def run(self, arguments: list[str], *, input_text: str | None = None, timeout: int = 20) -> str:
        operation = docker_operation(arguments)
        try:
            result = subprocess.run(  # noqa: S603 - fixed docker binary/argv, never a shell
                ["docker", "--context", "default", *arguments],  # noqa: S607
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                env=self.environment,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GateError(f"Local Docker {operation} did not complete.") from error
        if result.returncode != 0 or len(result.stdout) > 1_000_000:
            raise GateError(f"Local Docker {operation} failed; no runtime pass was recorded.")
        return result.stdout.strip()


def object_output(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise GateError("Docker or runtime returned malformed proof data.") from error
    if not isinstance(value, dict):
        raise GateError("Docker or runtime returned malformed proof data.")
    return value


def validate_inputs(admin_image: str, coach_image: str, release_id: str) -> None:
    if not SHA.fullmatch(release_id) or not all(
        IMAGE.fullmatch(image) for image in (admin_image, coach_image)
    ):
        raise GateError("Use a full release SHA and exact sha256 image IDs, never tags.")
    if admin_image == coach_image:
        raise GateError("Admin and Coach must be distinct compiled release images.")


def inspect_image(docker: Docker, image: str, surface: str, release_id: str) -> None:
    value = object_output(docker.run(["image", "inspect", "--format", "{{json .}}", image]))
    config = value.get("Config") or {}
    port = "3001" if surface == "admin" else "3002"
    if (
        value.get("Id") != image
        or value.get("Os") != "linux"
        or value.get("Architecture") != "amd64"
        or config.get("User") != "node"
        or config.get("WorkingDir") != "/app"
        or config.get("Cmd") != ["node", f"apps/{surface}-web/server.js"]
        or config.get("Entrypoint") != ["docker-entrypoint.sh"]
        or config.get("Volumes")
        or (config.get("Labels") or {}).get(REVISION_LABEL) != release_id
    ):
        raise GateError(
            "Image identity, baked revision or original non-root startup contract differs."
        )
    environment: dict[str, str] = {}
    for entry in config.get("Env") or []:
        name, separator, value = entry.partition("=")
        if not separator or name in environment:
            raise GateError("Release image environment is malformed.")
        environment[name] = value
    allowed = {
        "PATH",
        "NODE_VERSION",
        "YARN_VERSION",
        "HOSTNAME",
        "NODE_ENV",
        "PORT",
        "NEXT_TELEMETRY_DISABLED",
    }
    if set(environment) - allowed or any(
        environment.get(key) != value
        for key, value in {
            "HOSTNAME": "0.0.0.0",  # noqa: S104 - inspect baked metadata; probe overrides to loopback
            "NODE_ENV": "production",
            "PORT": port,
            "NEXT_TELEMETRY_DISABLED": "1",
        }.items()
    ):
        raise GateError("Release image contains unexpected or non-production environment settings.")


def owned_container(docker: Docker, name: str, owner: str, image: str) -> dict[str, Any] | None:
    found = docker.run(
        ["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", f"name=^/{name}$"]
    )
    if not found:
        return None
    if not CONTAINER.fullmatch(found):
        raise GateError("Cannot establish one exact proof container identity.")
    value = object_output(docker.run(["container", "inspect", "--format", "{{json .}}", found]))
    if (
        value.get("Id") != found
        or value.get("Name") != "/" + name
        or value.get("Image") != image
        or (value.get("Config", {}).get("Labels") or {}).get(OWNER_LABEL) != owner
    ):
        raise GateError("Container ownership differs; refusing to stop or remove it.")
    return value


def prove_image(
    docker: Docker, image: str, surface: str, release_id: str, probe: str
) -> dict[str, Any]:
    owner = uuid4().hex
    name = f"ac-release-proof-{owner}-{surface}"
    # An unexpected pre-existing name is never claimed or cleaned up by this invocation.
    existing = docker.run(
        ["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", f"name=^/{name}$"]
    )
    if existing:
        raise GateError("Proof container name already exists; no existing container was changed.")
    try:
        created = docker.run(
            [
                "create",
                "--pull",
                "never",
                "--name",
                name,
                "--label",
                f"{OWNER_LABEL}={owner}",
                "--network",
                "none",
                "--read-only",
                "--init",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=64m",  # noqa: S108 - disposable container tmpfs
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--pids-limit",
                "256",
                "--log-driver",
                "none",
                "--env",
                "HOSTNAME=127.0.0.1",
                "--env",
                "NODE_ENV=production",
                "--env",
                "NODE_OPTIONS=--max-old-space-size=384",
                "--env",
                "AC_INTERNAL_API_HOST=api.production.ac.internal.invalid",
                "--env",
                "AC_INTERNAL_API_URL=http://api.production.ac.internal.invalid:8000",
                "--env",
                "AC_COACH_APP_URL=https://coach.authorityclosers.com",
                # Prove a stale development flag cannot unlock compiled production routes.
                "--env",
                "AC_DEV_LOCAL_SANDBOX_ENABLED=true",
                image,
            ]
        )
        if not CONTAINER.fullmatch(created):
            raise GateError("Docker did not return an exact created container identity.")
        actual = owned_container(docker, name, owner, image)
        if actual is None or actual["Id"] != created:
            raise GateError("The created container could not be independently identified.")
        docker.run(["start", created])
        running = owned_container(docker, name, owner, image)
        if running is None or not running.get("State", {}).get("Running"):
            raise GateError("Standalone server exited before its runtime probes.")
        result = object_output(
            docker.run(
                [
                    "exec",
                    "--interactive",
                    "--env",
                    "AC_RELEASE_IMAGE_PROBE=1",
                    created,
                    "node",
                    "--input-type=module",
                    "-",
                    surface,
                ],
                input_text=probe,
                timeout=60,
            )
        )
        expected = {
            "non-root-linux-node",
            "loopback-health",
            "public-health-denied",
            "forwarded-health-denied",
            "anonymous-pages-denied",
            "production-login",
            "compiled-js-css",
            "anonymous-api-denied" if surface == "admin" else "development-api-unavailable",
        }
        if surface == "admin":
            expected.add("coach-redirect-no-query-or-write-replay")
        if (
            set(result) != {"surface", "checks", "compiled_assets", "api_auth_exercised"}
            or result.get("surface") != surface
            or not isinstance(result.get("checks"), list)
            or len(result["checks"]) != len(expected)
            or set(result["checks"]) != expected
            or type(result.get("compiled_assets")) is not int
            or not 2 <= result["compiled_assets"] <= 64
            or result.get("api_auth_exercised") is not False
        ):
            raise GateError("Runtime probe did not prove every required compiled-image check.")
        running = owned_container(docker, name, owner, image)
        if running is None or not running.get("State", {}).get("Running"):
            raise GateError("Standalone server exited during runtime verification.")
        return {"image_id": image, **result}
    finally:
        # Covers create/start/probe timeout ambiguity without broad names, pruning or rm globs.
        actual = owned_container(docker, name, owner, image)
        if actual is not None:
            docker.run(["rm", "--force", actual["Id"]])


def verify(docker: Docker, admin_image: str, coach_image: str, release_id: str) -> dict[str, Any]:
    validate_inputs(admin_image, coach_image, release_id)
    if sys.platform != "linux":
        raise GateError(
            "Exact release-image runtime proof requires a Linux host; no pass recorded."
        )
    endpoint = docker.run(
        ["context", "inspect", "default", "--format", "{{.Endpoints.docker.Host}}"]
    )
    if endpoint != "unix:///var/run/docker.sock":
        raise GateError(
            "Runtime gate requires the local Linux Docker socket, never a remote daemon."
        )
    if docker.run(["info", "--format", "{{.OSType}}"]) != "linux":
        raise GateError("Runtime gate requires Linux containers.")
    for surface, image in (("admin", admin_image), ("coach", coach_image)):
        inspect_image(docker, image, surface, release_id)
    probe = PROBE.read_text(encoding="utf-8")
    results = [
        prove_image(docker, image, surface, release_id, probe)
        for surface, image in (("admin", admin_image), ("coach", coach_image))
    ]
    return {
        "status": "passed",
        "source": "exact-linux-release-images",
        "release_id": release_id,
        "probe_sha256": hashlib.sha256(probe.encode()).hexdigest(),
        "api_auth_exercised": False,
        "surfaces": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-image", required=True)
    parser.add_argument("--coach-image", required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    try:
        proof = verify(Docker(), args.admin_image, args.coach_image, args.release_id)
    except GateError as error:
        print(
            f"Release image runtime gate failed: {error} No auth/API proof claimed.",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print(
            "Release image runtime gate failed; publication is blocked. No auth/API proof claimed.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
