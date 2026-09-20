from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
INSTALLER = APPLICATION / "scripts" / "install-application-release.sh"
VALIDATOR = APPLICATION / "scripts" / "sales-xray-hosted.py"
WORKER_OVERLAY = ROOT / "infra" / "conversation-worker" / "compose.hosted.yaml"
RELEASE_ID = "a" * 40
OPERATIONS_TENANT = "10000000-0000-4000-8000-000000000001"


@pytest.fixture
def activation_root(tmp_path: Path) -> Iterator[Path]:
    """Exercise the real root trust boundary under the dedicated Linux CI gate."""

    if os.name != "posix":
        yield tmp_path
        return
    if os.geteuid() != 0:
        if os.environ.get("AC_REQUIRE_HOSTED_ACTIVATION_ROOT_TEST") == "1":
            pytest.fail("The required hosted activation proof must run as root")
        pytest.skip("root-owned activation paths are exercised by the required Linux gate")
    # /tmp and runner homes are intentionally untrusted by the production validator.
    # Use a disposable tree below /run; never relax the validator for a test host.
    with tempfile.TemporaryDirectory(prefix="ac-hosted-activation-", dir="/run") as folder:
        yield Path(folder)


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
        f"AC_COMPOSE_PROJECT=ac-application-{environment}\n",
        encoding="utf-8",
    )
    (release / "release-images.env").write_text("", encoding="utf-8")

    approval = tmp_path / "approval.json"
    approval.write_bytes(
        _json_bytes(
            {
                "schema": "ac.sales-xray.hosted-approval/1",
                "environment": environment,
                "provider_control_tenant_id": OPERATIONS_TENANT,
            }
        )
    )
    env_file = tmp_path / "compose.env"
    service = tmp_path / "service.json"
    paths = {
        "service": service,
        "approval": approval,
        "database": tmp_path / "database-url",
        "storage": tmp_path / "storage",
        "scratch": tmp_path / "scratch",
        "socket": tmp_path / "socket",
        "elevenlabs": tmp_path / "elevenlabs",
        "deepgram": tmp_path / "deepgram",
        "groq": tmp_path / "groq",
        "gemini": tmp_path / "gemini",
        "challenge": tmp_path / "challenge-secret",
        "infisical": tmp_path / "infisical",
        "env": env_file,
    }
    service.write_bytes(
        _json_bytes(
            {
                "schema_version": "ac.sales_xray.worker_service/1",
                "environment": environment,
                "release_id": release_id,
                "operations_tenant_id": OPERATIONS_TENANT,
                "sales_xray_enabled": True,
                "bootstrap_only": False,
                "sales_xray_approval_path": "/run/ac-sales-xray/approval.json",
                "sales_xray_approval_sha256": hashlib.sha256(approval.read_bytes()).hexdigest(),
                "sales_xray_storage_root": _portable(paths["storage"]),
                "sales_xray_scratch_root": _portable(paths["scratch"]),
                "database_url_file": "/run/ac-sales-xray/database-url",
                "native_socket_path": _portable(paths["socket"] / "native.sock"),
                "native_image_ref": "sha256:" + "b" * 64,
                "providers": [
                    {
                        "credential_ref": "ref:elevenlabs",
                        "provider_id": "elevenlabs",
                        "executable": "/opt/infisical",
                        "project_ref": "project",
                        "environment_ref": "dev",
                        "secret_path_ref": "/sales-xray-test/elevenlabs",
                        "token_file_ref": "/run/ac-sales-xray/identities/elevenlabs/token",
                    },
                    {
                        "credential_ref": "ref:groq",
                        "provider_id": "groq",
                        "executable": "/opt/infisical",
                        "project_ref": "project",
                        "environment_ref": "dev",
                        "secret_path_ref": "/sales-xray-test/groq",
                        "token_file_ref": "/run/ac-sales-xray/identities/groq/token",
                    },
                ],
            }
        )
    )
    paths["challenge"].write_bytes(b"synthetic-turnstile-secret\n")
    if os.name == "posix":
        os.chown(paths["challenge"], 10001, 0)
        paths["challenge"].chmod(0o400)
    env_values = {
        "AC_XRAY_APPROVAL_FILE": _portable(approval),
        "AC_XRAY_APPROVAL_SHA256": hashlib.sha256(approval.read_bytes()).hexdigest(),
        "AC_XRAY_ACQUISITION_ENABLED": "true",
        "AC_XRAY_DATABASE_URL_FILE": _portable(paths["database"]),
        "AC_XRAY_ELEVENLABS_IDENTITY_DIR": _portable(paths["elevenlabs"]),
        "AC_XRAY_DEEPGRAM_IDENTITY_DIR": _portable(paths["deepgram"]),
        "AC_XRAY_GROQ_IDENTITY_DIR": _portable(paths["groq"]),
        "AC_XRAY_GEMINI_IDENTITY_DIR": _portable(paths["gemini"]),
        "AC_XRAY_CHALLENGE_SECRET_FILE": _portable(paths["challenge"]),
        "AC_XRAY_CHALLENGE_SITE_KEY": "synthetic-public-site-key",
        "AC_XRAY_ACQUISITION_POLICY_REVISION": "test-policy-v1",
        "AC_XRAY_NATIVE_IMAGE_REF": "sha256:" + "b" * 64,
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
    if os.name == "posix":
        for trusted_file in (approval, service, env_file, descriptor_file, digest_file):
            trusted_file.chmod(0o444)
    return release, paths


def _validator_result(
    release: Path,
    environment: str = "staging",
    operations_tenant_id: str | None = OPERATIONS_TENANT,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VALIDATOR), "compose-inputs", str(release), environment]
    if operations_tenant_id is not None:
        command.extend(["--operations-tenant-id", operations_tenant_id])
    return subprocess.run(  # noqa: S603 - fixed validator and test-controlled release
        command,
        capture_output=True,
        check=False,
        text=True,
    )


def _refresh_activation_inputs(paths: dict[str, Path]) -> None:
    """Rebind the disposable descriptor after a controlled fixture mutation."""

    service = json.loads(paths["service"].read_bytes())
    approval_sha = hashlib.sha256(paths["approval"].read_bytes()).hexdigest()
    service["sales_xray_approval_sha256"] = approval_sha
    paths["service"].write_bytes(_json_bytes(service))
    env_values = dict(
        line.split("=", 1) for line in paths["env"].read_text(encoding="utf-8").splitlines()
    )
    env_values["AC_XRAY_SERVICE_SHA256"] = hashlib.sha256(paths["service"].read_bytes()).hexdigest()
    env_values["AC_XRAY_APPROVAL_SHA256"] = approval_sha
    paths["env"].write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(env_values.items())),
        encoding="utf-8",
    )
    descriptor = json.loads(paths["descriptor"].read_bytes())
    descriptor["compose_env_sha256"] = hashlib.sha256(paths["env"].read_bytes()).hexdigest()
    descriptor["service_config_sha256"] = env_values["AC_XRAY_SERVICE_SHA256"]
    descriptor["approval_sha256"] = env_values["AC_XRAY_APPROVAL_SHA256"]
    paths["descriptor"].write_bytes(_json_bytes(descriptor))
    paths["digest"].write_bytes(
        (hashlib.sha256(paths["descriptor"].read_bytes()).hexdigest() + "\n").encode("ascii")
    )


def test_source_overlay_and_per_environment_capabilities_are_archive_inputs() -> None:
    overlay = APPLICATION / "compose.sales-xray-hosted.yaml"
    assert overlay.read_bytes() == WORKER_OVERLAY.read_bytes()
    for environment in ("staging", "production"):
        capability_path = APPLICATION / "capabilities" / f"sales-xray-hosted-{environment}.json"
        capability = json.loads(capability_path.read_text(encoding="utf-8"))
        assert capability == {
            "schema_version": "ac.sales_xray.hosted_policy/1",
            "environment": environment,
            "enabled": True,
            "activation_file_template": (
                "/etc/authority-closers/sales-xray/{environment}/activation-{release_id}.json"
            ),
            "activation_sha256_file_template": (
                "/etc/authority-closers/sales-xray/{environment}/"
                "activation-{release_id}.json.sha256"
            ),
            "previous_release_policy": "exact_target_release",
        }


def test_installer_repairs_worker_manifest_metadata_before_compose() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "--repair-worker-metadata" in installer


def test_hosted_validator_projects_only_target_release_inputs(activation_root: Path) -> None:
    release, paths = _make_release(activation_root)

    result = _validator_result(release)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(release / "compose.sales-xray-hosted.yaml"),
        str(paths["env"]),
        "sales-xray-hosted",
    ]


def test_hosted_projection_repairs_worker_manifest_readability(
    activation_root: Path,
) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("worker manifest ownership is a POSIX root projection")
    release, paths = _make_release(activation_root)
    os.chown(paths["service"], 0, 0)
    paths["service"].chmod(0o440)

    result = subprocess.run(  # noqa: S603 - fixed validator and synthetic test inputs
        [
            sys.executable,
            str(VALIDATOR),
            "compose-inputs",
            str(release),
            "staging",
            "--operations-tenant-id",
            OPERATIONS_TENANT,
            "--repair-worker-metadata",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    metadata = paths["service"].stat()
    assert metadata.st_uid == 0
    assert metadata.st_gid == 10001
    assert stat.S_IMODE(metadata.st_mode) == 0o440


def test_hosted_validator_supports_the_production_policy_shape(activation_root: Path) -> None:
    release, paths = _make_release(activation_root, environment="production")

    result = _validator_result(release, "production")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(release / "compose.sales-xray-hosted.yaml"),
        str(paths["env"]),
        "sales-xray-hosted",
    ]


def test_hosted_validator_accepts_terminal_blank_lines_from_approval_export(
    activation_root: Path,
) -> None:
    release, paths = _make_release(activation_root, environment="production")
    _refresh_activation_inputs(paths)
    paths["env"].write_bytes(paths["env"].read_bytes() + b"\n\n")
    descriptor = json.loads(paths["descriptor"].read_bytes())
    descriptor["compose_env_sha256"] = hashlib.sha256(paths["env"].read_bytes()).hexdigest()
    paths["descriptor"].write_bytes(_json_bytes(descriptor))
    paths["digest"].write_bytes(
        (hashlib.sha256(paths["descriptor"].read_bytes()).hexdigest() + "\n").encode("ascii")
    )

    result = _validator_result(release, "production")

    assert result.returncode == 0, result.stderr


def test_hosted_validator_accepts_explicit_inert_bootstrap(activation_root: Path) -> None:
    release, paths = _make_release(activation_root)
    service = json.loads(paths["service"].read_bytes())
    service["bootstrap_only"] = True
    service["providers"] = []
    paths["service"].write_bytes(_json_bytes(service))
    approval = json.loads(paths["approval"].read_bytes())
    approval.update({"allowances": [], "internal_tester_accounts": [], "stages": []})
    paths["approval"].write_bytes(_json_bytes(approval))
    env = dict(line.split("=", 1) for line in paths["env"].read_text().splitlines())
    env["AC_XRAY_ACQUISITION_ENABLED"] = "false"
    paths["env"].write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(env.items())), encoding="utf-8"
    )
    _refresh_activation_inputs(paths)

    result = _validator_result(release)

    assert result.returncode == 0, result.stderr


def test_hosted_validator_rejects_nonempty_bootstrap_authority(activation_root: Path) -> None:
    release, paths = _make_release(activation_root)
    service = json.loads(paths["service"].read_bytes())
    service["bootstrap_only"] = True
    service["providers"] = []
    paths["service"].write_bytes(_json_bytes(service))
    approval = json.loads(paths["approval"].read_bytes())
    approval.update({"allowances": [{"synthetic": "must-not-authorize"}], "stages": []})
    paths["approval"].write_bytes(_json_bytes(approval))
    env = dict(line.split("=", 1) for line in paths["env"].read_text().splitlines())
    env["AC_XRAY_ACQUISITION_ENABLED"] = "false"
    paths["env"].write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(env.items())), encoding="utf-8"
    )
    _refresh_activation_inputs(paths)

    assert _validator_result(release).returncode != 0


def test_hosted_validator_rejects_bootstrap_acquisition_mismatch(activation_root: Path) -> None:
    release, paths = _make_release(activation_root)
    service = json.loads(paths["service"].read_bytes())
    service["bootstrap_only"] = True
    service["providers"] = []
    paths["service"].write_bytes(_json_bytes(service))
    approval = json.loads(paths["approval"].read_bytes())
    approval.update({"allowances": [], "stages": []})
    paths["approval"].write_bytes(_json_bytes(approval))
    env = dict(line.split("=", 1) for line in paths["env"].read_text().splitlines())
    env["AC_XRAY_ACQUISITION_ENABLED"] = "true"
    paths["env"].write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(env.items())), encoding="utf-8"
    )
    _refresh_activation_inputs(paths)

    assert _validator_result(release).returncode != 0


def test_rollback_target_uses_its_own_release_descriptor(activation_root: Path) -> None:
    candidate, candidate_paths = _make_release(activation_root / "candidate", release_id="a" * 40)
    previous, previous_paths = _make_release(activation_root / "previous", release_id="d" * 40)

    candidate_result = _validator_result(candidate)
    previous_result = _validator_result(previous)

    assert candidate_result.returncode == 0, candidate_result.stderr
    assert previous_result.returncode == 0, previous_result.stderr
    assert candidate_result.stdout.splitlines()[1] == str(candidate_paths["env"])
    assert previous_result.stdout.splitlines()[1] == str(previous_paths["env"])
    assert candidate_paths["descriptor"] != previous_paths["descriptor"]


def test_hosted_validator_preserves_older_release_without_policy(activation_root: Path) -> None:
    release, _ = _make_release(activation_root)
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
    activation_root: Path, mutation: Callable[[dict[str, object]], None]
) -> None:
    release, paths = _make_release(activation_root)
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


def test_hosted_validator_rejects_compose_environment_key_injection(activation_root: Path) -> None:
    release, paths = _make_release(activation_root)
    paths["env"].write_text(
        paths["env"].read_text(encoding="utf-8") + "AC_DATABASE_URL=secret\n", encoding="utf-8"
    )
    result = _validator_result(release)
    assert result.returncode != 0


def test_hosted_validator_requires_managed_runtime_operations_scope(activation_root: Path) -> None:
    release, _ = _make_release(activation_root)

    missing = _validator_result(release, operations_tenant_id=None)
    mismatched = _validator_result(
        release, operations_tenant_id="20000000-0000-4000-8000-000000000002"
    )

    assert missing.returncode != 0
    assert mismatched.returncode != 0
    assert OPERATIONS_TENANT not in missing.stderr
    assert OPERATIONS_TENANT not in mismatched.stderr


@pytest.mark.parametrize(
    ("key", "replacement"),
    (
        ("AC_XRAY_NATIVE_IMAGE_REF", "sha256:" + "f" * 64),
        ("AC_XRAY_NATIVE_IMAGE_REF", "latest"),
        ("AC_XRAY_CHALLENGE_SITE_KEY", "https://untrusted.example"),
        ("AC_XRAY_ACQUISITION_POLICY_REVISION", "../foreign-policy"),
    ),
)
def test_preflight_rejects_unbound_native_or_acquisition_inputs(
    activation_root: Path, key: str, replacement: str
) -> None:
    release, paths = _make_release(activation_root)
    env = dict(line.split("=", 1) for line in paths["env"].read_text().splitlines())
    env[key] = replacement
    paths["env"].write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    descriptor = json.loads(paths["descriptor"].read_bytes())
    descriptor["compose_env_sha256"] = hashlib.sha256(paths["env"].read_bytes()).hexdigest()
    paths["descriptor"].write_bytes(_json_bytes(descriptor))
    paths["digest"].write_bytes(
        (hashlib.sha256(paths["descriptor"].read_bytes()).hexdigest() + "\n").encode("ascii")
    )

    assert _validator_result(release).returncode != 0


def test_hosted_validator_accepts_api_readable_challenge_file(activation_root: Path) -> None:
    release, paths = _make_release(activation_root)

    result = _validator_result(release)

    assert result.returncode == 0, result.stderr
    assert paths["challenge"].name == "challenge-secret"
    assert paths["challenge"].is_file()
    if os.name == "posix":
        info = paths["challenge"].stat()
        assert info.st_uid == 10001
        assert info.st_gid == 0
        assert stat.S_IMODE(info.st_mode) == 0o400
        assert stat.S_IMODE(paths["challenge"].parent.stat().st_mode) == 0o700


def test_hosted_validator_rejects_missing_or_directory_challenge_file(
    activation_root: Path,
) -> None:
    release, paths = _make_release(activation_root)
    paths["challenge"].unlink()
    paths["challenge"].mkdir()

    result = _validator_result(release)

    assert result.returncode != 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX challenge ownership boundary")
def test_hosted_validator_rejects_unreadable_or_symlinked_challenge_file(
    activation_root: Path,
) -> None:
    release, paths = _make_release(activation_root)
    os.chown(paths["challenge"], 0, 0)
    paths["challenge"].chmod(0o400)
    assert _validator_result(release).returncode != 0

    paths["challenge"].unlink()
    referent = paths["challenge"].with_name("foreign-secret")
    referent.write_bytes(b"foreign\n")
    paths["challenge"].symlink_to(referent)
    assert _validator_result(release).returncode != 0


def test_hosted_validator_uses_explicit_managed_scope_over_ambient_value(
    activation_root: Path,
) -> None:
    release, _ = _make_release(activation_root)
    command = [
        sys.executable,
        str(VALIDATOR),
        "compose-inputs",
        str(release),
        "staging",
        "--operations-tenant-id",
        OPERATIONS_TENANT,
    ]
    environment = os.environ.copy()
    environment["AC_OPERATIONS_TENANT_ID"] = "20000000-0000-4000-8000-000000000002"
    result = subprocess.run(  # noqa: S603 - fixed validator and test-controlled release
        command,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and mode boundary")
def test_hosted_validator_rejects_writable_external_activation_parent(
    activation_root: Path,
) -> None:
    release, paths = _make_release(activation_root)
    assert _validator_result(release).returncode == 0
    parent = paths["descriptor"].parent
    original_mode = parent.stat().st_mode & 0o7777
    parent.chmod(original_mode | 0o002)
    try:
        result = _validator_result(release)
    finally:
        parent.chmod(original_mode)
    assert result.returncode != 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and mode boundary")
@pytest.mark.parametrize("path_key", ("descriptor", "digest", "env", "service", "approval"))
@pytest.mark.parametrize("tamper", ("foreign_owner", "owner_writable", "hardlink"))
def test_hosted_validator_rejects_untrusted_activation_files(
    activation_root: Path, path_key: str, tamper: str
) -> None:
    release, paths = _make_release(activation_root)
    assert _validator_result(release).returncode == 0
    target = paths[path_key]
    if tamper == "foreign_owner":
        os.chown(target, 65534, 65534)
    elif tamper == "owner_writable":
        target.chmod(0o644)
    else:
        target.with_name(target.name + ".alias").hardlink_to(target)
    assert _validator_result(release).returncode != 0


def test_installer_compose_for_uses_target_release_overlay_and_clears_ambient_inputs(
    activation_root: Path,
) -> None:
    release, paths = _make_release(activation_root)
    fake_bin = activation_root / "bin"
    fake_bin.mkdir()
    capture = activation_root / "compose-args"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$@" > "$AC_CAPTURE"\n'
        'printf \'ambient=%s\\n\' "${AC_XRAY_SERVICE_CONFIG-unset}" >> "$AC_CAPTURE"\n',
        encoding="utf-8",
        newline="\n",
    )
    fake_docker.chmod(0o755)
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        f'#!/usr/bin/env bash\nexec {shlex.quote(_bash_path(Path(sys.executable)))} "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    fake_python.chmod(0o755)
    installer = INSTALLER.read_text(encoding="utf-8")
    start = installer.index("sales_xray_hosted_inputs=()")
    end = installer.index('\n\ncompose_for "$release_dir" config --quiet', start)
    functions = installer[start:end]
    filesystem_start = installer.index("filesystem_media_compose_file_for() {")
    filesystem_end = installer.index(
        "\n\nvalidate_filesystem_media_activation() {", filesystem_start
    )
    filesystem_selector = installer[filesystem_start:filesystem_end]
    script = f"""#!/usr/bin/env bash
set -euo pipefail
target_environment=staging
release_dir={shlex.quote(str(release).replace("\\\\", "/"))}
compose_project=ac-application-staging
with_practice_pilot_scope() {{ "$@"; }}
with_release_secrets() {{ env AC_OPERATIONS_TENANT_ID="$TEST_OPERATIONS_TENANT" "$@"; }}
export PATH={shlex.quote(_bash_path(fake_bin))}:$PATH
export AC_XRAY_SERVICE_CONFIG=https://ambient.invalid
{filesystem_selector}
{functions}
compose_for "$release_dir" config
"""
    environment = os.environ.copy()
    environment["AC_CAPTURE"] = _bash_path(capture)
    environment["TEST_OPERATIONS_TENANT"] = OPERATIONS_TENANT
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
    env_values = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "--env-file"]
    assert str(release / "compose.sales-xray-hosted.yaml") in file_values
    assert str(paths["env"]) in env_values
    assert args[args.index("--profile") + 1] == "sales-xray-hosted"
    assert args[-1] == "ambient=unset"


def test_installer_gives_hosted_worker_the_full_graceful_drain_timeout(
    tmp_path: Path,
) -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    start = installer.index("sales_xray_hosted_inputs=()")
    end = installer.index('\n\ncompose_for "$release_dir" config --quiet', start)
    functions = installer[start:end]
    capture = tmp_path / "drain-calls"
    release = tmp_path / ("e" * 40)
    script = f"""#!/usr/bin/env bash
set -euo pipefail
{functions}
sales_xray_hosted_enabled() {{ return 0; }}
compose_for() {{
  printf 'CALL\\n' >> "$AC_CAPTURE"
  printf '%s\\n' "$@" >> "$AC_CAPTURE"
  if [[ "$2" == ps && "$3" == --all ]]; then
    printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'
  fi
}}
docker() {{
  printf 'DOCKER\\n' >> "$AC_CAPTURE"
  printf '%s\\n' "$@" >> "$AC_CAPTURE"
  printf 'exited %s\\n' "$TEST_EXIT"
}}
stop_hosted_sales_xray_worker {shlex.quote(str(release).replace("\\\\", "/"))}
"""
    environment = os.environ.copy()
    environment["AC_CAPTURE"] = _bash_path(capture)
    environment["TEST_EXIT"] = "0"
    result = subprocess.run(  # noqa: S603 - fixed Bash function and test-controlled paths
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    calls = capture.read_text(encoding="utf-8").splitlines()
    assert calls[:6] == [
        "CALL",
        str(release),
        "stop",
        "--timeout",
        "960",
        "sales-xray-worker",
    ]
    assert calls[6:] == [
        "CALL",
        str(release),
        "ps",
        "--status",
        "running",
        "--services",
        "CALL",
        str(release),
        "ps",
        "--all",
        "--quiet",
        "sales-xray-worker",
        "DOCKER",
        "inspect",
        "--type",
        "container",
        "--format",
        "{{.State.Status}} {{.State.ExitCode}}",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]


def test_installer_rejects_hosted_worker_that_survives_drain(tmp_path: Path) -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    start = installer.index("sales_xray_hosted_inputs=()")
    end = installer.index('\n\ncompose_for "$release_dir" config --quiet', start)
    functions = installer[start:end]
    release = tmp_path / ("f" * 40)
    script = f"""#!/usr/bin/env bash
set -euo pipefail
{functions}
sales_xray_hosted_enabled() {{ return 0; }}
compose_for() {{
  if [[ "$2" == ps && "$3" == --all ]]; then
    printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'
  fi
}}
docker() {{ printf 'exited 137\\n'; }}
stop_hosted_sales_xray_worker {shlex.quote(str(release).replace("\\\\", "/"))}
"""
    result = subprocess.run(  # noqa: S603 - fixed Bash function and test-controlled paths
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode != 0
    assert "did not exit cleanly" in result.stderr


def test_installer_stops_core_then_drains_hosted_then_stops_web(tmp_path: Path) -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    start = installer.index("sales_xray_hosted_inputs=()")
    end = installer.index('\n\ncompose_for "$release_dir" config --quiet', start)
    functions = installer[start:end]
    capture = tmp_path / "ordered-calls"
    release = tmp_path / ("b" * 40)
    release_arg = str(release).replace(chr(92), "/")
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        + functions
        + "\nsales_xray_hosted_enabled() { return 0; }\n"
        + "compose_for() {\n"
        + '  printf \'%s\\n\' "$@" >> "$AC_CAPTURE"\n'
        + '  if [[ "$2" == ps && "$3" == --all ]]; then\n'
        + "    printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'\n"
        + "  fi\n}\n"
        + "docker() { printf 'exited 0\\n'; }\n"
        + f"stop_application_services_with_hosted_drain {release_arg} true\n"
    )
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
    calls = capture.read_text(encoding="utf-8").splitlines()
    core_index = calls.index("api")
    hosted_index = calls.index("sales-xray-worker")
    web_index = calls.index("learner-web")
    assert calls[core_index - 2 : core_index] == ["--timeout", "30"]
    assert calls[hosted_index - 2 : hosted_index] == ["--timeout", "960"]
    assert calls[web_index - 2 : web_index] == ["--timeout", "30"]
    assert core_index < hosted_index < web_index


def test_installer_does_not_fence_after_failed_hosted_drain(tmp_path: Path) -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    rollback_start = installer.index("rollback_release()")
    start = installer.index('  if [[ "$rollback_failed" == 0 ]]; then', rollback_start)
    end = installer.index('  if [[ "$rollback_failed" == 0 && "$backup_ready"', start)
    rollback_fence_block = installer[start:end]
    capture = tmp_path / "fence-calls"
    state = tmp_path / "rollback-state"
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "rollback_failed=1\n"
        "database_mutation_started=1\n"
        "rollback_fenced=0\n"
        "backup_ready=1\n"
        "set_database_writer_access() { printf 'fence\\n' >> \"$AC_CAPTURE\"; }\n"
        + rollback_fence_block
        + 'printf \'%s %s\\n\' "$rollback_failed" "$rollback_fenced" > "$AC_STATE"\n'
    )
    environment = os.environ.copy()
    environment["AC_CAPTURE"] = _bash_path(capture)
    environment["AC_STATE"] = _bash_path(state)
    result = subprocess.run(  # noqa: S603 - fixed Bash block and test-controlled paths
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert state.read_text(encoding="utf-8").strip() == "1 0"
    assert not capture.exists()


def test_installer_lifecycle_names_hosted_worker_for_drain_and_restart() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "stop_hosted_sales_xray_worker" in installer
    assert "stop --timeout 960 sales-xray-worker" in installer
    assert 'compose_for "$target_release" stop --timeout 30 api worker' in installer
    assert 'stop_application_services_with_hosted_drain "$writer_release" false' in installer
    assert "runtime_workers+=(sales-xray-worker)" in installer
    assert '"${hosted_profiles[@]}"' in installer
    assert "--remove-orphans" in installer
