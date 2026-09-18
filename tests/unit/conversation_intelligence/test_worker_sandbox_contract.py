"""Static candidate-policy checks only; these tests never invoke Docker."""

from __future__ import annotations

import ast
import re
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "infra" / "conversation-worker" / "Dockerfile"
README = ROOT / "infra" / "conversation-worker" / "README.md"
SOURCE_HASH = "40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3"


def _instructions(text: str) -> list[str]:
    flattened = re.sub(r"\\\r?\n\s*", " ", text)
    return [
        line.strip()
        for line in flattened.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _candidate_violations(dockerfile: str, readme: str) -> set[str]:
    instructions = _instructions(dockerfile)
    violations = set()
    sources = [line.split()[1] for line in instructions if line.startswith("FROM ")]
    if (
        len(sources) != 2
        or any(
            not re.fullmatch(
                r"python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}",
                source,
            )
            for source in sources
        )
        or len(set(sources)) != 1
    ):
        violations.add("unpinned-base")
    if "USER 10001:10001" not in instructions:
        violations.add("root-runtime")
    if any(line.startswith(("ADD ", "EXPOSE ", "VOLUME ", "ARG ")) for line in instructions):
        violations.add("unexpected-image-capability")
    context_copies = [
        line for line in instructions if line.startswith("COPY ") and "--from=" not in line
    ]
    allowed_sources = {
        "packages/python/ac_platform/__init__.py",
        "packages/python/ac_platform/conversation_intelligence/__init__.py",
        "packages/python/ac_platform/conversation_intelligence/__main__.py",
        "packages/python/ac_platform/conversation_intelligence/signals.py",
        "native/audioatlas/atlas_dsp.cpp",
        "native/audioatlas/LICENSE",
        "native/audioatlas/source_provenance.json",
    }
    copied = {item for line in context_copies for item in line.split()[1:-1]}
    if copied != allowed_sources:
        violations.add("broad-context-copy")
    if SOURCE_HASH not in dockerfile or "build_native()" not in dockerfile:
        violations.add("unverified-native")
    runtime = dockerfile.split(" AS runtime", 1)[-1]
    if "g++=" in runtime or "pip install" in runtime or "ffmpeg=7:5.1.9-0+deb12u1" not in runtime:
        violations.add("unexpected-runtime-dependency")
    # Inspect the actual run code block, not prose mentioning unsafe flags as warnings.
    blocks = re.findall(r"```sh\n(.*?)\n```", readme, re.S)
    run = next((block for block in blocks if "docker run --rm --init" in block), "")
    required = {
        "--network=none",
        "--read-only",
        "--user=10001:10001",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=32",
        "--memory=768m",
        "--memory-swap=768m",
        "--cpus=1",
        "--ulimit=nofile=64:64",
        "--ulimit=core=0:0",
        "--ulimit=fsize=268435456:268435456",
        "--log-driver=none",
        "--pull=never",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--tmpfs=/work:rw,noexec,nosuid,nodev,size=512m,uid=10001,gid=10001,mode=0700",
        "target=/input/source.media,readonly,bind-propagation=rprivate",
        "target=/output,bind-propagation=rprivate",
        '"--rate", "16000"',
        "timeout --signal=TERM --kill-after=5s 750s",
        "docker rm --force",
        "filesystem.f_frsize * filesystem.f_blocks <= 67108864",
    }
    if any(flag not in run for flag in required):
        violations.add("missing-runtime-boundary")
    forbidden = {
        "--privileged",
        "--network=host",
        "--pid=host",
        "--ipc=host",
        "--cap-add",
        "seccomp=unconfined",
        "/var/run/docker.sock",
        "--env-file",
    }
    if any(flag in run for flag in forbidden):
        violations.add("privilege-or-secret-escalation")
    if readme.count("container build/run/confinement unproven") != 1:
        violations.add("missing-proof-boundary")
    return violations


def test_offline_worker_candidate_preserves_runtime_boundaries() -> None:
    assert _candidate_violations(DOCKERFILE.read_text(), README.read_text()) == set()


def test_runtime_preflight_program_is_valid_python_and_calls_only_offline_cli() -> None:
    code = re.search(r'"\$AC_WORKER_IMAGE" -c \'\n(.*?)\n\'', README.read_text(), re.S)
    assert code is not None
    tree = ast.parse(code.group(1))
    imports = {node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)}
    assert imports == {"os", "shutil", "stat", "subprocess", "sys"}
    assert "ac_platform.conversation_intelligence" in code.group(1)
    for required in (
        "CapEff",
        "NoNewPrivs",
        "Seccomp",
        "memory.max",
        "memory.swap.max",
        "pids.max",
        "cpu.max",
        "/proc/self/mountinfo",
        "/sys/class/net",
    ):
        assert required in code.group(1)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
    ]
    assert len(calls) == 1
    assert {keyword.arg for keyword in calls[0].keywords} == {"check", "timeout"}


@pytest.mark.parametrize(
    "weakened",
    [
        "none",
        "root-user",
        "capability",
        "privileges",
        "seccomp",
        "network",
        "memory",
        "swap",
        "pids",
        "cpu",
        "root-write",
        "source-write",
        "scratch-exec",
        "scratch-size",
        "output-size",
        "output-mode",
        "optimized-python",
    ],
)
def test_fixed_preflight_rejects_simulated_weaker_effective_controls(weakened: str) -> None:
    """Pure mocked preflight regression; never a claim about actual kernel enforcement."""
    program = re.search(r'"\$AC_WORKER_IMAGE" -c \'\n(.*?)\n\'', README.read_text(), re.S)
    assert program is not None
    tree = ast.parse(program.group(1))
    preflight = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            function = node.value.func
            if isinstance(function, ast.Attribute) and function.attr == "run":
                break
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            preflight.append(node)
    metadata = {
        "/proc/self/status": "CapEff:0\nCapPrm:0\nCapBnd:0\nCapAmb:0\nNoNewPrivs:1\nSeccomp:2",
        "/sys/fs/cgroup/memory.max": "805306368",
        "/sys/fs/cgroup/memory.swap.max": "0",
        "/sys/fs/cgroup/pids.max": "32",
        "/sys/fs/cgroup/cpu.max": "100000 100000",
        "/proc/self/mountinfo": "\n".join(
            [
                "1 0 0:1 / / ro - overlay overlay ro",
                "2 0 0:2 / /input/source.media ro - ext4 source ro",
                "3 0 0:3 / /work rw,nosuid,nodev,noexec - tmpfs tmpfs rw",
                "4 0 0:4 / /tmp rw,nosuid,nodev,noexec - tmpfs tmpfs rw",
            ]
        ),
    }
    replacements = {
        "capability": ("/proc/self/status", "CapEff:0", "CapEff:1"),
        "privileges": ("/proc/self/status", "NoNewPrivs:1", "NoNewPrivs:0"),
        "seccomp": ("/proc/self/status", "Seccomp:2", "Seccomp:0"),
        "memory": ("/sys/fs/cgroup/memory.max", "805306368", "1610612736"),
        "swap": ("/sys/fs/cgroup/memory.swap.max", "0", "4096"),
        "pids": ("/sys/fs/cgroup/pids.max", "32", "64"),
        "cpu": ("/sys/fs/cgroup/cpu.max", "100000 100000", "200000 100000"),
        "root-write": ("/proc/self/mountinfo", "/ / ro", "/ / rw"),
        "source-write": (
            "/proc/self/mountinfo",
            "/input/source.media ro",
            "/input/source.media rw",
        ),
        "scratch-exec": ("/proc/self/mountinfo", "rw,nosuid,nodev,noexec", "rw,nosuid,nodev"),
    }
    if weakened in replacements:
        path, before, after = replacements[weakened]
        metadata[path] = metadata[path].replace(before, after)

    class FakePath:
        def __init__(self, path: str) -> None:
            self.path = path

        def __truediv__(self, child: str) -> FakePath:
            return FakePath(self.path + "/" + child)

        def read_text(self) -> str:
            return metadata[self.path]

    sizes = {"/work": 536870912, "/tmp": 16777216, "/output": 67108864}  # noqa: S108
    if weakened == "scratch-size":
        sizes["/work"] *= 2
    if weakened == "output-size":
        sizes["/output"] *= 2
    environment: dict[str, Any] = {
        "os": SimpleNamespace(
            umask=lambda value: None,
            getuid=lambda: 0 if weakened == "root-user" else 10001,
            getgid=lambda: 10001,
            listdir=lambda path: ["lo", "eth0"] if weakened == "network" else ["lo"],
            statvfs=lambda path: SimpleNamespace(f_frsize=4096, f_blocks=sizes[path] // 4096),
            stat=lambda path: SimpleNamespace(
                st_mode=0o755 if weakened == "output-mode" else 0o700
            ),
        ),
        "stat": stat,
        "Path": FakePath,
        "sys": SimpleNamespace(flags=SimpleNamespace(optimize=weakened == "optimized-python")),
    }
    compiled = compile(
        ast.Module(body=preflight, type_ignores=[]), "fixed-preflight-fixture", "exec"
    )
    if weakened == "none":
        exec(compiled, environment)  # noqa: S102 -- authored preflight AST; all effects mocked
    else:
        with pytest.raises((AssertionError, RuntimeError)):
            exec(compiled, environment)  # noqa: S102 -- authored preflight AST; all effects mocked


@pytest.mark.parametrize(
    "flag",
    [
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--memory=768m",
        "--pids-limit=32",
        "--cpus=1",
        "target=/input/source.media,readonly,bind-propagation=rprivate",
    ],
)
def test_static_policy_detects_removed_security_controls(flag: str) -> None:
    modified = README.read_text().replace(flag, "")
    assert "missing-runtime-boundary" in _candidate_violations(DOCKERFILE.read_text(), modified)


@pytest.mark.parametrize(
    "unsafe",
    ["--privileged", "--env-file=/private/provider.env", "--security-opt=seccomp=unconfined"],
)
def test_static_policy_detects_injected_unsafe_runtime_flags(unsafe: str) -> None:
    modified = README.read_text().replace(
        "docker run --rm --init", f"docker run --rm --init {unsafe}"
    )
    assert "privilege-or-secret-escalation" in _candidate_violations(
        DOCKERFILE.read_text(), modified
    )


def test_static_policy_detects_broad_copy_and_unpinned_image() -> None:
    modified = DOCKERFILE.read_text() + "\nCOPY . /app/\n"
    assert "broad-context-copy" in _candidate_violations(modified, README.read_text())
    modified = re.sub(r"@sha256:[0-9a-f]{64}", "", DOCKERFILE.read_text())
    assert "unpinned-base" in _candidate_violations(modified, README.read_text())
