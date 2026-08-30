from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
COMPOSE = (APPLICATION / "compose.yaml").read_text(encoding="utf-8")
WEB_DOCKERFILE = (APPLICATION / "Dockerfile.web").read_text(encoding="utf-8")
PYTHON_DOCKERFILE = (APPLICATION / "Dockerfile.python").read_text(encoding="utf-8")
CADDYFILE = (ROOT / "infra" / "vps-foundation" / "compose" / "foundation" / "Caddyfile").read_text(
    encoding="utf-8"
)
INSTALLER = (APPLICATION / "scripts" / "install-application-release.sh").read_text(encoding="utf-8")
INFISICAL_RUNNER = (ROOT / "infra" / "vps-foundation" / "scripts" / "ac-infisical-run").read_text(
    encoding="utf-8"
)
WORKFLOW = (ROOT / ".github" / "workflows" / "application.yml").read_text(encoding="utf-8")


@pytest.mark.parametrize("dockerfile", [WEB_DOCKERFILE, PYTHON_DOCKERFILE])
def test_application_base_images_are_content_addressed(dockerfile: str) -> None:
    image_arguments = re.findall(r"^ARG [A-Z_]*IMAGE=(\S+)$", dockerfile, flags=re.MULTILINE)

    assert image_arguments
    assert all("@sha256:" in image for image in image_arguments)
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in image_arguments)


def test_runtime_containers_are_not_privileged_or_host_published() -> None:
    assert "privileged:" not in COMPOSE
    assert "network_mode: host" not in COMPOSE
    assert "ports:" not in COMPOSE
    assert "no-new-privileges:true" in COMPOSE
    assert "cap_drop:\n    - ALL" in COMPOSE
    assert "read_only: true" in COMPOSE
    assert '"--forwarded-allow-ips", "*"' not in PYTHON_DOCKERFILE
    assert '"--no-proxy-headers"' in PYTHON_DOCKERFILE
    assert "container_name:" not in COMPOSE
    assert "build:" not in COMPOSE
    assert COMPOSE.count("pull_policy: never") == 5


def test_release_fails_closed_on_identity_and_database_secrets() -> None:
    required_markers = (
        "AC_RELEASE_ID:?",
        "AC_DATABASE_URL:?",
        "AC_DATABASE_MIGRATOR_URL:?",
        "AC_SESSION_TOKEN_PEPPER:?",
        "AC_OAUTH_TRANSACTION_SECRET:?",
        "AC_POSTGRES_OWNER_PASSWORD:?",
        "AC_DB_MIGRATOR_PASSWORD:?",
        "AC_DB_RUNTIME_PASSWORD:?",
        "AC_DB_BACKUP_PASSWORD:?",
        "AC_API_IMAGE:?",
        "AC_LEARNER_IMAGE:?",
        "AC_ADMIN_IMAGE:?",
    )

    for marker in required_markers:
        assert marker in COMPOSE

    assert "AC_EXTERNAL_SIDE_EFFECTS_HOLD:-true" in COMPOSE
    assert "AC_EMAIL_PROVIDER:-fake" in COMPOSE
    assert len(re.findall(r"^\s+AC_DATABASE_MIGRATOR_URL:", COMPOSE, re.MULTILINE)) == 1
    assert "x-migration-environment: &migration-environment" in COMPOSE
    assert "migrate:\n" in COMPOSE
    assert "<<: *migration-environment" in COMPOSE


def test_database_and_edge_networks_are_explicitly_separated() -> None:
    assert "/postgres:/var/lib/postgresql\n" in COMPOSE
    assert "/postgres:/var/lib/postgresql/data" not in COMPOSE
    assert "--auth-local=scram-sha-256" in COMPOSE
    assert re.search(r'^\s+test:\s*\["CMD-SHELL",\s*"pg_isready', COMPOSE, re.MULTILINE) is None
    assert "SELECT count(*) = 3 FROM pg_roles" in COMPOSE
    assert "data:\n    internal: true" in COMPOSE
    assert "app:\n    internal: true" in COMPOSE
    assert "name: ac_edge\n    external: true" in COMPOSE
    assert "name: ac_telemetry\n    external: true" in COMPOSE
    assert "AC_COMPOSE_PROJECT:?" in COMPOSE
    assert "AC_STATE_ROOT:?" in COMPOSE
    for alias in ("AC_EDGE_API_ALIAS:?", "AC_EDGE_LEARNER_ALIAS:?", "AC_EDGE_ADMIN_ALIAS:?"):
        assert alias in COMPOSE


def test_caddy_routes_only_named_application_hosts() -> None:
    for hostname, upstream in (
        ("app.authorityclosers.com", "ac-production-learner:3000"),
        ("admin.authorityclosers.com", "ac-production-admin:3001"),
        ("api.authorityclosers.com", "ac-production-api:8000"),
        ("staging.authorityclosers.com", "ac-staging-learner:3000"),
        ("admin-staging.authorityclosers.com", "ac-staging-admin:3001"),
        ("api-staging.authorityclosers.com", "ac-staging-api:8000"),
    ):
        assert f"host {hostname}" in CADDYFILE
        assert f"reverse_proxy {upstream}" in CADDYFILE

    assert "Strict-Transport-Security" in CADDYFILE
    assert "X-Content-Type-Options" in CADDYFILE
    assert CADDYFILE.count("path /v1/*") == 4
    assert CADDYFILE.count("reverse_proxy ac-production-api:8000") == 3
    assert CADDYFILE.count("reverse_proxy ac-staging-api:8000") == 3
    assert CADDYFILE.index("\thandle @learner_api {") < CADDYFILE.index("\thandle @learner {")
    assert CADDYFILE.index("\thandle @admin_api {") < CADDYFILE.index("\thandle @admin {")
    assert CADDYFILE.count("connect-src 'self';") == 4
    assert "connect-src 'self' https://api.authorityclosers.com" not in CADDYFILE
    for route in (
        "learner-production",
        "admin-production",
        "api-production",
        "learner-staging",
        "admin-staging",
        "api-staging",
    ):
        assert f'X-Authority-Closers-Route "{route}"' in CADDYFILE


def test_api_healthcheck_uses_canonical_trusted_host() -> None:
    assert "http://127.0.0.1:8000/health/ready" in COMPOSE
    assert "headers={'Host': os.environ['AC_API_HOST']}" in COMPOSE
    assert "AC_INTERNAL_API_HOST: ${AC_API_HOST:?" in COMPOSE


def test_admin_healthcheck_uses_loopback_only_health_boundary() -> None:
    assert "http://127.0.0.1:3001/healthz" in COMPOSE
    assert 'INTERNAL_HEALTH_HOSTS = new Set(["127.0.0.1:3001", "localhost:3001"])' in (
        ROOT / "apps" / "admin-web" / "proxy.ts"
    ).read_text(encoding="utf-8")


def test_environment_profiles_isolate_state_hosts_and_edge_aliases() -> None:
    staging = (APPLICATION / "environments" / "staging.env").read_text(encoding="utf-8")
    production = (APPLICATION / "environments" / "production.env").read_text(encoding="utf-8")

    assert "AC_STATE_ROOT=/srv/authority-closers/state/application/staging" in staging
    assert "AC_STATE_ROOT=/srv/authority-closers/state/application/production" in production
    assert "AC_API_HOST=api-staging.authorityclosers.com" in staging
    assert "AC_API_HOST=api.authorityclosers.com" in production
    assert "AC_EDGE_API_ALIAS=ac-staging-api" in staging
    assert "AC_EDGE_API_ALIAS=ac-production-api" in production
    assert ".staging.authorityclosers.com" not in staging
    assert "AC_EXTERNAL_SIDE_EFFECTS_HOLD=true" in staging
    assert "AC_EXTERNAL_SIDE_EFFECTS_HOLD=true" in production


def test_release_is_built_off_host_and_installed_with_backup_and_rollback() -> None:
    assert "workflow_dispatch:" in WORKFLOW
    assert "packages: write" in WORKFLOW
    assert WORKFLOW.count("load: true") == 3
    assert "Refusing to overwrite immutable release tag" in WORKFLOW
    assert "release-images.env" in WORKFLOW
    assert 'tar --extract --to-stdout --file "$transport_tar" index.json' in WORKFLOW
    assert "transport_digest_for" in WORKFLOW
    assert "verify_transport_config" in WORKFLOW
    assert "OCI transport manifest does not reference the reviewed image config" in WORKFLOW
    assert "AC_API_IMAGE=%s" in WORKFLOW and "api_transport_digest" in WORKFLOW
    assert "Application deployment requires exact OCI transport manifest digests" in INSTALLER
    assert "max_artifact_bytes=450000000" in WORKFLOW
    assert "refusing upload above" in WORKFLOW
    assert "retention-days: 1" in WORKFLOW
    assert "docker build" not in INSTALLER
    assert "docker load" in INSTALLER
    assert "pg_dump" in INSTALLER and "--create" in INSTALLER
    assert "pg_restore" in INSTALLER and "--clean" in INSTALLER
    assert "ROLLBACK" in INSTALLER
    assert "AC_EXTERNAL_SIDE_EFFECTS_HOLD" in COMPOSE
    assert "/usr/local/sbin/ac-infisical-run" in INSTALLER
    assert 'find "$stage_dir/postgres/init" -type d -exec chmod 0755' in INSTALLER
    assert 'find "$stage_dir/postgres/init" -type f -exec chmod 0644' in INSTALLER
    postgres_bootstrap = (APPLICATION / "postgres" / "init" / "001-roles.sh").read_text(
        encoding="utf-8"
    )
    assert "GRANT USAGE, SELECT ON SEQUENCES TO ac_backup" in postgres_bootstrap


def test_infisical_runner_accepts_only_named_environment_and_safe_path() -> None:
    assert "dev|staging|prod" in INFISICAL_RUNNER
    assert 'secret_path="${AC_INFISICAL_PATH:-/}"' in INFISICAL_RUNNER
    assert '--env="$secret_environment"' in INFISICAL_RUNNER
    assert '--path="$secret_path"' in INFISICAL_RUNNER
