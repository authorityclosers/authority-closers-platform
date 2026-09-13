from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
INSTALLER = APPLICATION / "scripts" / "install-application-release.sh"
VALIDATOR = APPLICATION / "scripts" / "sales-xray-hosted.py"
RELEASE_ID = "a" * 40
OPERATIONS_TENANT = "10000000-0000-4000-8000-000000000001"


def _bash_executable() -> str:
    git = shutil.which("git")
    candidates = []
    if git is not None and sys.platform == "win32":
        candidates.append(Path(git).parent.parent / "bin" / "bash.exe")
    discovered = shutil.which("bash")
    if discovered is not None:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    pytest.fail("Bash is required for the installer lifecycle regression")


def _portable(path: Path) -> str:
    return path.as_posix()


def _bash_path(path: Path) -> str:
    raw = path.as_posix()
    if len(raw) >= 2 and raw[1] == ":":
        return f"/{raw[0].lower()}{raw[2:]}"
    return raw


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _make_release(
    tmp_path: Path,
    *,
    release_id: str = RELEASE_ID,
    environment: str = "staging",
) -> tuple[Path, dict[str, Path]]:
    release = tmp_path / release_id
    (release / "scripts").mkdir(parents=True)
    (release / "capabilities").mkdir()
    (release / "environments").mkdir()
    (release / "RELEASE-COMMIT").write_bytes((release_id + "\n").encode("ascii"))
    (release / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (release / "compose.sales-xray-hosted.yaml").write_bytes(
        (APPLICATION / "compose.sales-xray-hosted.yaml").read_bytes()
    )
    (release / "scripts" / "sales-xray-hosted.py").write_bytes(VALIDATOR.read_bytes())
    (release / "environments" / f"{environment}.env").write_text(
        f"AC_COMPOSE_PROJECT=ac-application-{environment}\n"
        f"AC_OPERATIONS_TENANT_ID={OPERATIONS_TENANT}\n",
        encoding="utf-8",
    )
    (release / "release-images.env").write_text("", encoding="utf-8")

    service = tmp_path / "service.json"
    service.write_bytes(
        _json_bytes(
            {
                "environment": environment,
                "native_image_ref": "sha256:" + "b" * 64,
                "operations_tenant_id": OPERATIONS_TENANT,
                "release_id": release_id,
            }
        )
    )
    approval = tmp_path / "approval.json"
    approval.write_bytes(_json_bytes({"provider_control_tenant_id": OPERATIONS_TENANT}))
    env_file = tmp_path / "compose.env"
    paths = {
        "service": service,
        "approval": approval,
        "database": tmp_path / "database-url",
        "storage": tmp_path / "storage",
        "scratch": tmp_path / "scratch",
        "socket": tmp_path / "socket",
        "elevenlabs": tmp_path / "elevenlabs",
        "groq": tmp_path / "groq",
        "infisical": tmp_path / "infisical",
        "env": env_file,
    }
    env_values = {
        "AC_XRAY_APPROVAL_FILE": _portable(approval),
        "AC_XRAY_APPROVAL_SHA256": hashlib.sha256(approval.read_bytes()).hexdigest(),
        "AC_XRAY_DATABASE_URL_FILE": _portable(paths["database"]),
        "AC_XRAY_ELEVENLABS_IDENTITY_DIR": _portable(paths["elevenlabs"]),
        "AC_XRAY_GROQ_IDENTITY_DIR": _portable(paths["groq"]),
        "AC_XRAY_INFISICAL_BINARY": _portable(paths["infisical"]),
        "AC_XRAY_NATIVE_SOCKET_DIR": _portable(paths["socket"]),
        "AC_XRAY_SCRATCH_ROOT": _portable(paths["scratch"]),
        "AC_XRAY_SERVICE_CONFIG": _portable(service),
        "AC_XRAY_SERVICE_SHA256": hashlib.sha256(service.read_bytes()).hexdigest(),
        "AC_XRAY_STORAGE_ROOT": _portable(paths["storage"]),
    }
    env_file.write_text(
        "".join(f"{key}={env_values[key]}\n" for key in sorted(env_values)), encoding="utf-8"
    )
    descriptor = {
        "schema_version": "ac.sales_xray.hosted_activation/1",
        "environment": environment,
        "release_id": release_id,
        "compose_overlay": "compose.sales-xray-hosted.yaml",
        "compose_profile": "sales-xray-hosted",
        "compose_env_file": _portable(env_file),
        "compose_env_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
        "service_config_file": _portable(service),
        "service_config_sha256": env_values["AC_XRAY_SERVICE_SHA256"],
        "approval_file": _portable(approval),
        "approval_sha256": env_values["AC_XRAY_APPROVAL_SHA256"],
        "native_image_ref": "sha256:" + "b" * 64,
        "native_image_config_id": "sha256:" + "c" * 64,
        "helper_unit": f"ac-sales-xray-native-helper@{environment}.service",
        "previous_release_policy": "exact_target_release",
    }
    descriptor_file = tmp_path / f"activation-{environment}-{release_id}.json"
    descriptor_file.write_bytes(_json_bytes(descriptor))
    digest_file = tmp_path / f"activation-{environment}-{release_id}.json.sha256"
    digest_file.write_bytes(
        (hashlib.sha256(descriptor_file.read_bytes()).hexdigest() + "\n").encode("ascii")
    )
    capability = {
        "schema_version": "ac.sales_xray.hosted_policy/1",
        "environment": environment,
        "enabled": True,
        "activation_file_template": _portable(
            tmp_path / "activation-{environment}-{release_id}.json"
        ),
        "activation_sha256_file_template": _portable(
            tmp_path / "activation-{environment}-{release_id}.json.sha256"
        ),
        "previous_release_policy": "exact_target_release",
    }
    (release / "capabilities" / f"sales-xray-hosted-{environment}.json").write_bytes(
        _json_bytes(capability)
    )
    paths["descriptor"] = descriptor_file
    paths["digest"] = digest_file
    return release, paths


def _validator_result(
    release: Path, environment: str = "staging"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed validator and test-controlled release
        [sys.executable, str(VALIDATOR), "compose-inputs", str(release), environment],
        capture_output=True,
        check=False,
        text=True,
    )


def test_hosted_validator_projects_only_target_release_inputs(tmp_path: Path) -> None:
    release, paths = _make_release(tmp_path)

    result = _validator_result(release)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(release / "compose.sales-xray-hosted.yaml"),
        str(paths["env"]),
        "sales-xray-hosted",
    ]


def test_hosted_validator_supports_the_production_policy_shape(tmp_path: Path) -> None:
    release, paths = _make_release(tmp_path, environment="production")

    result = _validator_result(release, "production")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(release / "compose.sales-xray-hosted.yaml"),
        str(paths["env"]),
        "sales-xray-hosted",
    ]


def test_rollback_target_uses_its_own_release_descriptor(tmp_path: Path) -> None:
    candidate, candidate_paths = _make_release(tmp_path / "candidate", release_id="a" * 40)
    previous, previous_paths = _make_release(tmp_path / "previous", release_id="d" * 40)

    candidate_result = _validator_result(candidate)
    previous_result = _validator_result(previous)

    assert candidate_result.returncode == 0, candidate_result.stderr
    assert previous_result.returncode == 0, previous_result.stderr
    assert candidate_result.stdout.splitlines()[1] == str(candidate_paths["env"])
    assert previous_result.stdout.splitlines()[1] == str(previous_paths["env"])
    assert candidate_paths["descriptor"] != previous_paths["descriptor"]


def test_hosted_validator_preserves_older_release_without_policy(tmp_path: Path) -> None:
    release, _ = _make_release(tmp_path)
    (release / "capabilities" / "sales-xray-hosted-staging.json").unlink()

    result = _validator_result(release)

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.__setitem__("release_id", "d" * 40),
        lambda value: value.__setitem__("native_image_ref", "latest"),
        lambda value: value.__setitem__("previous_release_policy", "current_release"),
    ),
)
def test_hosted_validator_rejects_descriptor_identity_tampering(
    tmp_path: Path, mutation: Callable[[dict[str, object]], None]
) -> None:
    release, paths = _make_release(tmp_path)
    descriptor = json.loads(paths["descriptor"].read_text(encoding="utf-8"))
    mutation(descriptor)
    paths["descriptor"].write_bytes(_json_bytes(descriptor))
    # A release policy digest is immutable; changing only the external file must fail.
    result = _validator_result(release)
    assert result.returncode != 0

    # A policy owner may intentionally issue a new descriptor, but the descriptor
    # must still bind to this exact release and immutable image identities.
    paths["digest"].write_bytes(
        (hashlib.sha256(paths["descriptor"].read_bytes()).hexdigest() + "\n").encode("ascii")
    )
    result = _validator_result(release)
    assert result.returncode != 0


def test_hosted_validator_rejects_compose_environment_key_injection(tmp_path: Path) -> None:
    release, paths = _make_release(tmp_path)
    paths["env"].write_text(
        paths["env"].read_text(encoding="utf-8") + "AC_DATABASE_URL=secret\n", encoding="utf-8"
    )
    result = _validator_result(release)
    assert result.returncode != 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and mode boundary")
def test_hosted_validator_rejects_writable_external_activation_parent(tmp_path: Path) -> None:
    release, paths = _make_release(tmp_path)
    parent = paths["descriptor"].parent
    original_mode = parent.stat().st_mode & 0o7777
    parent.chmod(original_mode | 0o002)
    try:
        result = _validator_result(release)
    finally:
        parent.chmod(original_mode)
    assert result.returncode != 0


def test_installer_compose_for_uses_target_release_overlay_and_clears_ambient_inputs(
    tmp_path: Path,
) -> None:
    release, paths = _make_release(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "compose-args"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$AC_CAPTURE\"\n"
        "printf 'ambient=%s\\n' \"${AC_XRAY_SERVICE_CONFIG-unset}\" >> \"$AC_CAPTURE\"\n",
        encoding="utf-8",
        newline="\n",
    )
    fake_docker.chmod(0o755)
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        f"exec {shlex.quote(_bash_path(Path(sys.executable)))} \"$@\"\n",
        encoding="utf-8",
        newline="\n",
    )
    fake_python.chmod(0o755)
    installer = INSTALLER.read_text(encoding="utf-8")
    start = installer.index("sales_xray_hosted_inputs=()")
    end = installer.index('\n\ncompose_for "$release_dir" config --quiet', start)
    functions = installer[start:end]
    script = f"""#!/usr/bin/env bash
set -euo pipefail
target_environment=staging
release_dir={shlex.quote(str(release).replace('\\\\', '/'))}
compose_project=ac-application-staging
with_practice_pilot_scope() {{ "$@"; }}
export PATH={shlex.quote(_bash_path(fake_bin))}:$PATH
export AC_XRAY_SERVICE_CONFIG=https://ambient.invalid
{functions}
compose_for "$release_dir" config
"""
    environment = os.environ.copy()
    environment["AC_CAPTURE"] = _bash_path(capture)
    result = subprocess.run(  # noqa: S603 - fixed Bash function and test-controlled paths
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    args = capture.read_text(encoding="utf-8").splitlines()
    file_values = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "--file"]
    env_values = [
        args[index + 1] for index, value in enumerate(args[:-1]) if value == "--env-file"
    ]
    assert str(release / "compose.sales-xray-hosted.yaml") in file_values
    assert str(paths["env"]) in env_values
    assert args[args.index("--profile") + 1] == "sales-xray-hosted"
    assert args[-1] == "ambient=unset"


def test_installer_lifecycle_names_hosted_worker_for_drain_and_restart() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "rollback_services+=(sales-xray-worker)" in installer
    assert "containment_services+=(sales-xray-worker)" in installer
    assert "writer_services+=(sales-xray-worker)" in installer
    assert "runtime_workers+=(sales-xray-worker)" in installer
    assert '"${hosted_profiles[@]}"' in installer
    assert "--remove-orphans" in installer
