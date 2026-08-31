from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
COMPOSE_FILE = APPLICATION / "compose.yaml"
COMPOSE_TEXT = COMPOSE_FILE.read_text(encoding="utf-8")
DOCKER = shutil.which("docker.exe" if os.name == "nt" else "docker")

EXPECTED_INTERNAL_HOSTS = {
    "staging": "api.staging.ac.internal.invalid",
    "production": "api.production.ac.internal.invalid",
}
PROFILE_VARIABLES = {
    "AC_COMPOSE_PROJECT",
    "AC_ENVIRONMENT",
    "AC_STATE_ROOT",
    "AC_PUBLIC_APP_URL",
    "AC_ADMIN_APP_URL",
    "AC_API_URL",
    "AC_API_HOST",
    "AC_INTERNAL_API_HOST",
    "AC_TRUSTED_PROXY_ADDRESSES",
    "AC_EDGE_API_ALIAS",
    "AC_EDGE_LEARNER_ALIAS",
    "AC_EDGE_ADMIN_ALIAS",
    "AC_EXTERNAL_SIDE_EFFECTS_HOLD",
    "AC_EMAIL_PROVIDER",
    "AC_RESEND_API_KEY",
    "AC_RESEND_FROM",
    "AC_OPERATIONS_TENANT_ID",
}


def _compose_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key not in PROFILE_VARIABLES}
    environment.update(
        {
            "AC_RELEASE_ID": "a" * 40,
            "AC_API_IMAGE": "sha256:" + "a" * 64,
            "AC_LEARNER_IMAGE": "sha256:" + "b" * 64,
            "AC_ADMIN_IMAGE": "sha256:" + "c" * 64,
            "AC_DATABASE_URL": (
                "postgresql+psycopg://ac_runtime:fixture-runtime-password@postgres/ac_platform"
            ),
            "AC_DATABASE_MIGRATOR_URL": (
                "postgresql+psycopg://ac_migrator:fixture-migrator-password@postgres/ac_platform"
            ),
            "AC_SESSION_TOKEN_PEPPER": "fixture-session-pepper-value-at-least-32-bytes",
            "AC_OAUTH_TRANSACTION_SECRET": ("fixture-oauth-transaction-value-at-least-32-bytes"),
            "AC_EMAIL_CHALLENGE_SECRET": ("fixture-email-challenge-value-at-least-32-bytes"),
            "AC_GOOGLE_OAUTH_CLIENT_ID": "fixture.apps.googleusercontent.com",
            "AC_GOOGLE_OAUTH_CLIENT_SECRET": "fixture-google-secret",
            "AC_POSTGRES_OWNER_PASSWORD": "fixture-owner-password",
            "AC_DB_MIGRATOR_PASSWORD": "fixture-migrator-password",
            "AC_DB_RUNTIME_PASSWORD": "fixture-runtime-password",
            "AC_DB_BACKUP_PASSWORD": "fixture-backup-password",
            "AC_OPERATIONS_TENANT_ID": "33333333-3333-4333-8333-333333333333",
        }
    )
    return environment


def _render_compose(
    profile: str,
    *,
    environment_overrides: dict[str, str] | None = None,
    enabled_profiles: tuple[str, ...] = (),
) -> dict[str, object]:
    if DOCKER is None:
        pytest.fail("Docker CLI is required to render the application Compose contract")
    environment = _compose_environment()
    if environment_overrides is not None:
        environment.update(environment_overrides)
    command = [DOCKER, "compose"]
    for enabled_profile in enabled_profiles:
        command.extend(("--profile", enabled_profile))
    command.extend(
        (
            "--env-file",
            str(APPLICATION / "environments" / f"{profile}.env"),
            "--file",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        )
    )
    result = subprocess.run(  # noqa: S603 - fixed Docker CLI and repository inputs
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert isinstance(rendered, dict)
    return rendered


@pytest.mark.parametrize("profile", ["staging", "production"])
def test_compose_binds_resend_configuration_only_to_worker(profile: str) -> None:
    held_render = _render_compose(profile, enabled_profiles=("release",))
    held_services = held_render["services"]
    assert isinstance(held_services, dict)
    held_worker = held_services["worker"]
    assert isinstance(held_worker, dict)
    assert held_worker["environment"]["AC_EMAIL_PROVIDER"] == "fake"  # type: ignore[index]
    assert held_worker["environment"]["AC_RESEND_API_KEY"] == ""  # type: ignore[index]
    assert held_worker["environment"]["AC_RESEND_FROM"] == ""  # type: ignore[index]

    rendered = _render_compose(
        profile,
        environment_overrides={
            "AC_EMAIL_PROVIDER": "resend",
            "AC_RESEND_API_KEY": "fixture-resend-credential",
            "AC_RESEND_FROM": "Authority Closers <transactional@example.invalid>",
        },
        enabled_profiles=("release",),
    )
    services = rendered["services"]
    assert isinstance(services, dict)

    worker = services["worker"]
    api = services["api"]
    migrator = services["migrate"]
    assert isinstance(worker, dict)
    assert isinstance(api, dict)
    assert isinstance(migrator, dict)

    assert worker["environment"]["AC_EMAIL_PROVIDER"] == "resend"  # type: ignore[index]
    assert (  # type: ignore[index]
        worker["environment"]["AC_RESEND_API_KEY"] == "fixture-resend-credential"
    )
    assert (  # type: ignore[index]
        worker["environment"]["AC_RESEND_FROM"]
        == "Authority Closers <transactional@example.invalid>"
    )
    for service in (api, migrator):
        service_environment = service["environment"]
        assert isinstance(service_environment, dict)
        assert "AC_EMAIL_PROVIDER" not in service_environment
        assert "AC_RESEND_API_KEY" not in service_environment
        assert "AC_RESEND_FROM" not in service_environment
        assert "AC_PUBLIC_LEARNER_TENANT_ID" in service_environment

    for service_name in ("api", "migrate"):
        held_environment = held_services[service_name]["environment"]  # type: ignore[index]
        assert "AC_EMAIL_PROVIDER" not in held_environment
        assert "AC_RESEND_API_KEY" not in held_environment
        assert "AC_RESEND_FROM" not in held_environment


@pytest.mark.parametrize("profile", ["staging", "production"])
def test_compose_binds_admin_to_exact_reserved_internal_api_alias(profile: str) -> None:
    rendered = _render_compose(profile)
    services = rendered["services"]
    networks = rendered["networks"]
    assert isinstance(services, dict)
    assert isinstance(networks, dict)
    api = services["api"]
    admin = services["admin-web"]
    assert isinstance(api, dict)
    assert isinstance(admin, dict)
    expected_host = EXPECTED_INTERNAL_HOSTS[profile]

    assert api["networks"]["app"]["aliases"] == [expected_host]  # type: ignore[index]
    assert api["environment"]["AC_INTERNAL_API_HOST"] == expected_host  # type: ignore[index]
    assert api["environment"]["AC_SESSION_COOKIE_NAME"] == "__Host-ac_session"  # type: ignore[index]
    assert (  # type: ignore[index]
        api["environment"]["AC_OAUTH_TRANSACTION_COOKIE_NAME"] == "__Host-ac_oauth_transaction"
    )
    assert admin["environment"] == {  # type: ignore[index]
        "AC_INTERNAL_API_HOST": expected_host,
        "AC_INTERNAL_API_URL": f"http://{expected_host}:8000",
    }
    assert admin["depends_on"]["api"]["condition"] == "service_healthy"  # type: ignore[index]
    assert networks["app"]["internal"] is True  # type: ignore[index]
    assert "ports" not in api
    assert "ports" not in admin
    assert not any(
        alias.endswith("authorityclosers.com")
        for alias in api["networks"]["app"]["aliases"]  # type: ignore[index]
    )


def test_compose_requires_internal_host_and_profiles_fix_exact_environment_mapping() -> None:
    for profile, expected_host in EXPECTED_INTERNAL_HOSTS.items():
        profile_text = (APPLICATION / "environments" / f"{profile}.env").read_text(encoding="utf-8")
        assert profile_text.count(f"AC_INTERNAL_API_HOST={expected_host}\n") == 1

    assert "${AC_INTERNAL_API_HOST:?AC_INTERNAL_API_HOST is required}" in COMPOSE_TEXT
    assert "http://${AC_INTERNAL_API_HOST:" in COMPOSE_TEXT
    assert "http://${AC_API_HOST:" not in COMPOSE_TEXT
    assert "- ${AC_API_HOST:?AC_API_HOST is required}" not in COMPOSE_TEXT


def _run_docker(*arguments: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    if DOCKER is None:  # pragma: no cover - caller skips before invoking the helper
        raise RuntimeError("Docker CLI is unavailable")
    try:
        return subprocess.run(  # noqa: S603 - fixed or validated arguments
            [DOCKER, *arguments],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            args=error.cmd,
            returncode=124,
            stdout=error.stdout or "",
            stderr=error.stderr or "Docker probe timed out.",
        )


def test_reserved_alias_resolves_only_while_assigned_on_real_internal_docker_network() -> None:
    if DOCKER is None:
        pytest.skip("Docker CLI is unavailable")
    if _run_docker("info", "--format", "{{.ServerVersion}}").returncode != 0:
        pytest.skip("Docker daemon is unavailable")

    rendered = _render_compose("staging")
    services = rendered["services"]
    assert isinstance(services, dict)
    postgres = services["postgres"]
    api = services["api"]
    assert isinstance(postgres, dict)
    assert isinstance(api, dict)
    image = postgres["image"]
    alias = api["networks"]["app"]["aliases"][0]  # type: ignore[index]
    assert isinstance(image, str)
    assert isinstance(alias, str)
    assert re.fullmatch(r"api\.(staging|production)\.ac\.internal\.invalid", alias)
    if _run_docker("image", "inspect", image).returncode != 0:
        pytest.skip("The pinned PostgreSQL image is not present; refusing a network pull")

    suffix = uuid4().hex[:12]
    network = f"ac-admin-transport-{suffix}"
    target = f"ac-admin-target-{suffix}"
    assert re.fullmatch(r"ac-admin-(transport|target)-[0-9a-f]{12}", network)
    assert re.fullmatch(r"ac-admin-(transport|target)-[0-9a-f]{12}", target)

    created_network = False
    created_target = False
    try:
        result = _run_docker("network", "create", "--internal", network)
        assert result.returncode == 0, result.stderr
        created_network = True
        result = _run_docker(
            "run",
            "--detach",
            "--rm",
            "--pull",
            "never",
            "--name",
            target,
            "--network",
            network,
            "--network-alias",
            alias,
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            "sleep 30",
        )
        assert result.returncode == 0, result.stderr
        created_target = True

        resolved = _run_docker(
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            network,
            "--entrypoint",
            "/usr/bin/getent",
            image,
            "hosts",
            alias,
        )
        assert resolved.returncode == 0, resolved.stderr
        assert alias in resolved.stdout

        missing = _run_docker(
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            network,
            "--entrypoint",
            "/usr/bin/getent",
            image,
            "hosts",
            "api.missing.ac.internal.invalid",
        )
        assert missing.returncode != 0
        assert missing.stdout == ""
    finally:
        if created_target:
            _run_docker("rm", "--force", target)
        if created_network:
            _run_docker("network", "rm", network)
