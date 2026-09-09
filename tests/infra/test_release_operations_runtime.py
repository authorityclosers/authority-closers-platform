"""Controller/probe contract tests, not claims that release images ran locally."""

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_operations_runtime", ROOT / "scripts/verify-release-operations-images.py"
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
ADMIN = "sha256:" + "a" * 64
COACH = "sha256:" + "b" * 64
RELEASE = "c" * 40


def image_config(image, surface):
    return {
        "Id": image,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "User": "node",
            "WorkingDir": "/app",
            "Cmd": ["node", f"apps/{surface}-web/server.js"],
            "Entrypoint": ["docker-entrypoint.sh"],
            "Labels": {gate.REVISION_LABEL: RELEASE},
            "Env": [
                "PATH=/usr/local/bin:/usr/bin",
                "NODE_VERSION=24.19.0",
                "YARN_VERSION=1.22.22",
                "HOSTNAME=0.0.0.0",
                "NODE_ENV=production",
                "NEXT_TELEMETRY_DISABLED=1",
                "PORT=" + ("3001" if surface == "admin" else "3002"),
            ],
        },
    }


def probe_result(surface):
    checks = [
        "non-root-linux-node",
        "loopback-health",
        "public-health-denied",
        "forwarded-health-denied",
        "anonymous-pages-denied",
        "production-login",
        "compiled-js-css",
        "anonymous-api-denied" if surface == "admin" else "development-api-unavailable",
    ]
    if surface == "admin":
        checks.append("coach-redirect-no-query-or-write-replay")
    return {"surface": surface, "checks": checks, "compiled_assets": 4, "api_auth_exercised": False}


class FakeDocker:
    def __init__(self):
        self.commands = []
        self.containers = {}
        self.images = {ADMIN: image_config(ADMIN, "admin"), COACH: image_config(COACH, "coach")}
        self.failure = None
        self.probe_change = None
        self.endpoint = "unix:///var/run/docker.sock"

    def run(self, args, *, input_text=None, timeout=20):
        self.commands.append((args, input_text, timeout))
        if args[:2] == ["context", "inspect"]:
            return self.endpoint
        if args[0] == "info":
            return "linux"
        if args[:2] == ["image", "inspect"]:
            return json.dumps(self.images[args[-1]])
        if args[:2] == ["container", "ls"]:
            name = args[-1].removeprefix("name=^/").removesuffix("$")
            return self.containers.get(name, {}).get("Id", "")
        if args[:2] == ["container", "inspect"]:
            return json.dumps(
                next(item for item in self.containers.values() if item["Id"] == args[-1])
            )
        if args[0] == "create":
            if self.failure == "create-before":
                raise gate.GateError("synthetic failure")
            name = args[args.index("--name") + 1]
            owner = args[args.index("--label") + 1].split("=", 1)[1]
            identifier = ("d" if name.endswith("admin") else "e") * 64
            self.containers[name] = {
                "Id": identifier,
                "Name": "/" + name,
                "Image": args[-1],
                "Config": {"Labels": {gate.OWNER_LABEL: owner}},
                "State": {"Running": False},
            }
            if self.failure == "create-timeout-after":
                raise gate.GateError("synthetic timeout")
            return "ambiguous" if self.failure == "create-bad-id" else identifier
        if args[0] == "start":
            container = next(item for item in self.containers.values() if item["Id"] == args[-1])
            container["State"]["Running"] = self.failure != "early-exit"
            return args[-1]
        if args[0] == "exec":
            if self.failure == "changed-owner":
                next(iter(self.containers.values()))["Config"]["Labels"][gate.OWNER_LABEL] = (
                    "foreign"
                )
            if self.failure in {"probe-timeout", "changed-owner"}:
                raise gate.GateError("synthetic timeout")
            assert input_text and "verifyOperationsSurface" in input_text
            assert timeout == 60
            result = probe_result(args[-1])
            if self.probe_change:
                result.update(self.probe_change)
            return json.dumps(result)
        if args[0] == "rm":
            if self.failure == "cleanup":
                raise gate.GateError("synthetic cleanup failure")
            name = next(name for name, item in self.containers.items() if item["Id"] == args[-1])
            del self.containers[name]
            return args[-1]
        raise AssertionError(args)


@pytest.fixture
def docker(monkeypatch):
    monkeypatch.setattr(gate.sys, "platform", "linux")
    return FakeDocker()


def test_boots_two_exact_original_image_commands_and_cleans_only_owned_ids(docker):
    proof = gate.verify(docker, ADMIN, COACH, RELEASE)
    assert proof["status"] == "passed"
    assert proof["source"] == "exact-linux-release-images"
    assert proof["release_id"] == RELEASE and proof["api_auth_exercised"] is False
    assert [item["image_id"] for item in proof["surfaces"]] == [ADMIN, COACH]
    assert "anonymous-api-denied" in proof["surfaces"][0]["checks"]
    assert "development-api-unavailable" not in proof["surfaces"][0]["checks"]
    assert "development-api-unavailable" in proof["surfaces"][1]["checks"]
    assert "anonymous-api-denied" not in proof["surfaces"][1]["checks"]
    assert not docker.containers
    creates = [args for args, _, _ in docker.commands if args[0] == "create"]
    assert len(creates) == 2
    for args, image in zip(creates, (ADMIN, COACH), strict=True):
        assert args[-1] == image  # No replacement entrypoint or command appended.
        assert "--entrypoint" not in args and "--user" not in args
        assert "--publish" not in args and "-p" not in args and "--volume" not in args
        for flag, value in {
            "--network": "none",
            "--pull": "never",
            "--cap-drop": "ALL",
            "--security-opt": "no-new-privileges:true",
            "--memory": "512m",
            "--cpus": "1",
            "--pids-limit": "256",
            "--log-driver": "none",
            "--tmpfs": "/tmp:rw,noexec,nosuid,nodev,size=64m",  # noqa: S108 - container-only tmpfs
        }.items():
            assert args[args.index(flag) + 1] == value
        assert "--read-only" in args and "--init" in args
        assert "AC_DEV_LOCAL_SANDBOX_ENABLED=true" in args
    removed = [args[-1] for args, _, _ in docker.commands if args[0] == "rm"]
    assert removed == ["d" * 64, "e" * 64]


@pytest.mark.parametrize("image", ["latest", "repo:tag", "sha256:bad", "sha256:" + "A" * 64])
def test_refuses_tags_and_malformed_inputs_before_any_docker_call(docker, image):
    with pytest.raises(gate.GateError):
        gate.verify(docker, image, COACH, RELEASE)
    assert docker.commands == []


@pytest.mark.parametrize("failure", ["windows", "remote", "same-image", "short-release"])
def test_unsupported_host_or_identity_cannot_produce_an_artifact_pass(docker, monkeypatch, failure):
    if failure == "windows":
        monkeypatch.setattr(gate.sys, "platform", "win32")
    if failure == "remote":
        docker.endpoint = "ssh://remote.invalid"
    with pytest.raises(gate.GateError):
        gate.verify(
            docker,
            ADMIN,
            ADMIN if failure == "same-image" else COACH,
            "short" if failure == "short-release" else RELEASE,
        )
    assert not any(args[0] == "create" for args, _, _ in docker.commands)


@pytest.mark.parametrize(
    "failure",
    [
        "id",
        "os",
        "arch",
        "root",
        "cmd",
        "entrypoint",
        "revision",
        "missing-revision",
        "volume",
        "env",
        "duplicate-env",
    ],
)
def test_image_metadata_and_baked_revision_are_checked_before_start(docker, failure):
    image = docker.images[ADMIN]
    config = image["Config"]
    if failure == "id":
        image["Id"] = COACH
    elif failure == "os":
        image["Os"] = "windows"
    elif failure == "arch":
        image["Architecture"] = "arm64"
    elif failure == "root":
        config["User"] = "root"
    elif failure == "cmd":
        config["Cmd"] = ["node", "source-dev-server.js"]
    elif failure == "entrypoint":
        config["Entrypoint"] = ["replacement-server"]
    elif failure == "revision":
        config["Labels"][gate.REVISION_LABEL] = "f" * 40
    elif failure == "missing-revision":
        config["Labels"] = {}
    elif failure == "volume":
        config["Volumes"] = {"/data": {}}
    elif failure == "env":
        config["Env"].append("UNEXPECTED_CREDENTIAL=synthetic-never-print")
    else:
        config["Env"].append("NODE_ENV=development")
    with pytest.raises(gate.GateError) as error:
        gate.verify(docker, ADMIN, COACH, RELEASE)
    assert "synthetic-never-print" not in str(error.value)
    assert not any(args[0] == "create" for args, _, _ in docker.commands)


@pytest.mark.parametrize(
    "failure",
    ["create-before", "create-timeout-after", "create-bad-id", "early-exit", "probe-timeout"],
)
def test_failure_or_timeout_never_leaves_a_known_owned_container_running(docker, failure):
    docker.failure = failure
    with pytest.raises(gate.GateError):
        gate.verify(docker, ADMIN, COACH, RELEASE)
    assert not docker.containers
    removed = [args[-1] for args, _, _ in docker.commands if args[0] == "rm"]
    assert removed == ([] if failure == "create-before" else ["d" * 64])
    if failure == "early-exit":
        assert not any(args[0] == "exec" for args, _, _ in docker.commands)


def test_preexisting_name_is_not_adopted_or_removed(docker, monkeypatch):
    owner = "1" * 32
    monkeypatch.setattr(gate, "uuid4", lambda: SimpleNamespace(hex=owner))
    name = f"ac-release-proof-{owner}-admin"
    docker.containers[name] = {"Id": "f" * 64}
    with pytest.raises(gate.GateError, match="already exists"):
        gate.verify(docker, ADMIN, COACH, RELEASE)
    assert name in docker.containers
    assert not any(args[0] in {"create", "rm", "start"} for args, _, _ in docker.commands)


def test_changed_ownership_is_never_cleaned_up_as_this_gate_container(docker):
    docker.failure = "changed-owner"
    with pytest.raises(gate.GateError, match="ownership differs"):
        gate.verify(docker, ADMIN, COACH, RELEASE)
    assert len(docker.containers) == 1
    assert not any(args[0] == "rm" for args, _, _ in docker.commands)


def test_cleanup_failure_prevents_a_successful_proof_even_after_http_checks(docker):
    docker.failure = "cleanup"
    with pytest.raises(gate.GateError, match="cleanup failure"):
        gate.verify(docker, ADMIN, COACH, RELEASE)
    assert len(docker.containers) == 1
    assert [args[-1] for args, _, _ in docker.commands if args[0] == "rm"] == ["d" * 64]


@pytest.mark.parametrize(
    "change",
    [
        {"checks": []},
        {"api_auth_exercised": True},
        {"compiled_assets": 0},
        {"compiled_assets": True},
        {"surface": "learner"},
    ],
)
def test_missing_or_mislabelled_runtime_proof_blocks_publication(docker, change):
    docker.probe_change = change
    with pytest.raises(gate.GateError, match="every required"):
        gate.verify(docker, ADMIN, COACH, RELEASE)
    assert not docker.containers


@pytest.mark.parametrize("mode", ["timeout", "failure", "oserror"])
def test_real_subprocess_adapter_bounds_calls_and_sanitizes_failures(monkeypatch, mode):
    observed = {}
    monkeypatch.setenv("GH_TOKEN", "synthetic-never-print")
    monkeypatch.setenv("AC_DATABASE_URL", "synthetic-never-print")
    monkeypatch.setenv("DOCKER_HOST", "ssh://not-local.invalid")

    def fake_run(args, **kwargs):
        observed.update(args=args, **kwargs)
        if mode == "timeout":
            raise subprocess.TimeoutExpired(args, 20, output="synthetic-never-print")
        if mode == "oserror":
            raise OSError("synthetic-never-print")
        return SimpleNamespace(returncode=1, stdout="", stderr="synthetic-never-print")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    with pytest.raises(gate.GateError) as error:
        gate.Docker().run(["info"])
    assert "synthetic-never-print" not in str(error.value)
    assert observed["args"] == ["docker", "--context", "default", "info"]
    assert observed["timeout"] == 20 and observed["capture_output"] is True
    assert set(observed["env"]) <= {"HOME", "PATH", "LC_ALL"}


@pytest.mark.parametrize(
    ("arguments", "label"),
    [
        (["context", "inspect"], "local-context inspection"),
        (["info"], "engine inspection"),
        (["image", "inspect"], "image inspection"),
        (["container", "ls"], "proof-container lookup"),
        (["container", "inspect"], "proof-container inspection"),
        (["create"], "proof-container creation"),
        (["start"], "proof-container startup"),
        (["exec"], "runtime HTTP probe"),
        (["rm"], "proof-container cleanup"),
        ([], "command"),
    ],
)
def test_docker_diagnostic_labels_are_fixed_and_do_not_render_arguments(arguments, label):
    assert gate.docker_operation(arguments + ["synthetic-never-print"]) == label


def test_cli_surfaces_only_fixed_gate_errors(monkeypatch, capsys):
    monkeypatch.setattr(
        gate,
        "verify",
        lambda *_args: (_ for _ in ()).throw(gate.GateError("fixed runtime phase")),
    )
    monkeypatch.setattr(
        gate.sys,
        "argv",
        [
            "verify-release-operations-images.py",
            "--admin-image",
            ADMIN,
            "--coach-image",
            COACH,
            "--release-id",
            RELEASE,
        ],
    )

    assert gate.main() == 1
    assert capsys.readouterr().err == (
        "Release image runtime gate failed: fixed runtime phase No auth/API proof claimed.\n"
    )


def test_cli_does_not_surface_unexpected_exception_details(monkeypatch, capsys):
    monkeypatch.setattr(
        gate,
        "verify",
        lambda *_args: (_ for _ in ()).throw(ValueError("synthetic-never-print")),
    )
    monkeypatch.setattr(
        gate.sys,
        "argv",
        [
            "verify-release-operations-images.py",
            "--admin-image",
            ADMIN,
            "--coach-image",
            COACH,
            "--release-id",
            RELEASE,
        ],
    )

    assert gate.main() == 1
    assert "synthetic-never-print" not in capsys.readouterr().err


def test_ci_gate_is_before_publish_and_images_have_baked_revision_labels():
    workflow = (ROOT / ".github/workflows/application.yml").read_text()
    start = workflow.index("- name: Prove exact Linux operations image startup before publication")
    assert start < workflow.index("- name: Publish immutable SHA tags")
    block = workflow[start : workflow.index("- name: Publish immutable SHA tags")]
    assert "scripts/verify-release-operations-images.py" in block
    assert '--admin-image "$admin_id" --coach-image "$coach_id"' in block
    assert '--release-id "$GITHUB_SHA"' in block
    for surface in ("admin", "coach"):
        build = workflow.split(f"target: {surface}", 1)[1].split("cache-from:", 1)[0]
        assert "AC_RELEASE_ID=${{ github.sha }}" in build
        stage = (
            (ROOT / "infra/application/Dockerfile.web")
            .read_text()
            .split(f"AS {surface}", 1)[1]
            .split("FROM ", 1)[0]
        )
        assert "ARG AC_RELEASE_ID" in stage
        assert "LABEL org.opencontainers.image.revision=${AC_RELEASE_ID}" in stage


def test_node_probe_contracts_with_fake_http_not_a_live_artifact_claim():
    executable = os.environ.get("AC_TEST_NODE_EXECUTABLE") or shutil.which("node")
    if executable is None:
        pytest.skip("Node runtime missing; application CI installs Node before this suite")
    result = subprocess.run(  # noqa: S603 - fixed test file, no shell
        [executable, "--test", str(ROOT / "tests/infra/release-operations-probe.test.mjs")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
