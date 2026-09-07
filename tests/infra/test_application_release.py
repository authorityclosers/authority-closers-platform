from __future__ import annotations

import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
COMPOSE = (APPLICATION / "compose.yaml").read_text(encoding="utf-8")
APPLICATION_README = (APPLICATION / "README.md").read_text(encoding="utf-8")
APPLICATION_SECRETS = (APPLICATION / "SECRETS.md").read_text(encoding="utf-8")
WEB_DOCKERFILE = (APPLICATION / "Dockerfile.web").read_text(encoding="utf-8")
PYTHON_DOCKERFILE = (APPLICATION / "Dockerfile.python").read_text(encoding="utf-8")
CADDYFILE = (ROOT / "infra" / "vps-foundation" / "compose" / "foundation" / "Caddyfile").read_text(
    encoding="utf-8"
)
FOUNDATION_COMPOSE = (
    ROOT / "infra" / "vps-foundation" / "compose" / "foundation" / "compose.yaml"
).read_text(encoding="utf-8")
FOUNDATION_BOOTSTRAP = (
    ROOT / "infra" / "vps-foundation" / "scripts" / "bootstrap-host.sh"
).read_text(encoding="utf-8")
FOUNDATION_VALIDATOR = (
    ROOT / "infra" / "vps-foundation" / "scripts" / "validate-foundation.sh"
).read_text(encoding="utf-8")
INSTALLER = (APPLICATION / "scripts" / "install-application-release.sh").read_text(encoding="utf-8")
RELEASE_INPUT_PREPARER = (APPLICATION / "scripts" / "prepare-release-inputs.py").read_text(
    encoding="utf-8"
)
OAUTH_SECRET_PREFLIGHT = APPLICATION / "scripts" / "validate-google-oauth-secrets.py"
INFISICAL_RUNNER = (ROOT / "infra" / "vps-foundation" / "scripts" / "ac-infisical-run").read_text(
    encoding="utf-8"
)
WORKFLOW = (ROOT / ".github" / "workflows" / "application.yml").read_text(encoding="utf-8")
GIT_ATTRIBUTES = (ROOT / ".gitattributes").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
LOG_CREDENTIAL_QUERY_KEYS = {
    "code",
    "state",
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "token",
}


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
    pytest.fail("Bash is required for application profile tests")


def _installer_function(name: str, next_marker: str) -> str:
    start = INSTALLER.index(f"{name}() {{")
    return INSTALLER[start : INSTALLER.index(next_marker, start)]


def _run_profile_parser(
    tmp_path: Path,
    profile_bytes: bytes,
    *,
    target_environment: str = "staging",
) -> subprocess.CompletedProcess[str]:
    profile_file = tmp_path / f"{target_environment}.env"
    profile_file.write_bytes(profile_bytes)
    initialize_profile_contract = _installer_function(
        "initialize_release_profile_contract", "\n\nload_release_profile() {"
    )
    load_profile = _installer_function("load_release_profile", "\n\nprofile_value() {")
    profile_value = _installer_function("profile_value", "\n\nvalidate_release_profile() {")
    validate_profile = _installer_function(
        "validate_release_profile", "\n\nvalidate_release_profile\n"
    )
    script = f"""#!/usr/bin/env bash
set -euo pipefail
profile_file={shlex.quote(profile_file.as_posix())}
target_environment={shlex.quote(target_environment)}
declare -a profile_required_keys=()
declare -A profile_values=()
declare -A profile_allowed_keys=()
{initialize_profile_contract}
{load_profile}
{profile_value}
{validate_profile}
initialize_release_profile_contract
validate_release_profile
printf '%s,%s\n' "$external_side_effects_status" "$email_provider"
"""
    return subprocess.run(  # noqa: S603 - executable and profile are test-controlled
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
    )


def _run_compose_for_probe(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    release = tmp_path / "release"
    (release / "environments").mkdir(parents=True)
    (release / "environments" / "staging.env").write_bytes(
        (APPLICATION / "environments" / "staging.env").read_bytes()
    )
    (release / "release-images.env").write_text("", encoding="utf-8")
    (release / "compose.yaml").write_text(
        """name: ${AC_COMPOSE_PROJECT:?AC_COMPOSE_PROJECT is required}
services:
  probe:
    image: busybox
    environment:
      hold: ${AC_EXTERNAL_SIDE_EFFECTS_HOLD:-true}
      provider: ${AC_EMAIL_PROVIDER:-fake}
""",
        encoding="utf-8",
    )
    compose_for = _installer_function(
        "compose_for", '\n\ncompose_for "$release_dir" config --quiet'
    )
    script = f"""#!/usr/bin/env bash
set -euo pipefail
target_environment=staging
release_dir={shlex.quote(release.as_posix())}
compose_project=ac-application-staging
with_release_secrets() {{ "$@"; }}
export AC_EXTERNAL_SIDE_EFFECTS_HOLD=true
export AC_EMAIL_PROVIDER=fake
export COMPOSE_PROJECT_NAME=ac-application-production
{compose_for}
compose_for "$release_dir" config
"""
    return subprocess.run(  # noqa: S603 - executable and compose fixture are test-controlled
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
    )


def test_local_database_urls_match_the_ipv4_only_compose_publish_contract() -> None:
    database_lines = tuple(
        line
        for line in ENV_EXAMPLE.splitlines()
        if line.startswith(("AC_DATABASE_URL=", "AC_DATABASE_MIGRATOR_URL="))
    )

    assert len(database_lines) == 2
    assert all("@127.0.0.1:5432/ac_platform" in line for line in database_lines)
    assert all("@localhost:5432/" not in line for line in database_lines)


@pytest.mark.parametrize("dockerfile", [WEB_DOCKERFILE, PYTHON_DOCKERFILE])
def test_application_base_images_are_content_addressed(dockerfile: str) -> None:
    image_arguments = re.findall(r"^ARG [A-Z_]*IMAGE=(\S+)$", dockerfile, flags=re.MULTILINE)

    assert image_arguments
    assert all("@sha256:" in image for image in image_arguments)
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in image_arguments)


def test_learner_release_image_contains_reviewed_public_assets() -> None:
    assert "/workspace/apps/learner-web/public" in WEB_DOCKERFILE
    assert "./apps/learner-web/public" in WEB_DOCKERFILE
    assert WEB_DOCKERFILE.index("/workspace/apps/learner-web/public") < WEB_DOCKERFILE.index(
        "USER node"
    )


def test_runtime_containers_are_not_privileged_or_host_published() -> None:
    assert "privileged:" not in COMPOSE
    assert "network_mode: host" not in COMPOSE
    assert "ports:" not in COMPOSE
    assert "no-new-privileges:true" in COMPOSE
    assert "cap_drop:\n    - ALL" in COMPOSE
    assert "read_only: true" in COMPOSE
    assert '"--forwarded-allow-ips", "*"' not in PYTHON_DOCKERFILE
    assert '"--no-proxy-headers"' in PYTHON_DOCKERFILE
    assert '"--no-access-log"' in PYTHON_DOCKERFILE
    assert "container_name:" not in COMPOSE
    assert "build:" not in COMPOSE
    assert COMPOSE.count("pull_policy: never") == 5


def test_edge_and_application_logs_redact_oauth_and_media_credentials() -> None:
    assert '"--no-access-log"' in PYTHON_DOCKERFILE
    assert "request>uri query" in CADDYFILE
    assert CADDYFILE.count("import credential_query_redaction") == 2
    assert "log default {" in CADDYFILE.split("(base_security_headers)", maxsplit=1)[0]
    for field in LOG_CREDENTIAL_QUERY_KEYS:
        assert f"replace {field} REDACTED" in CADDYFILE
    assert "wrap json" in CADDYFILE


@pytest.fixture(scope="module")
def adapted_foundation_caddy_config() -> dict:
    """Adapt checked-in bytes; never start a server or contact the deployed VPS."""
    caddy = shutil.which("caddy")
    if caddy:
        command = [caddy, "adapt", "--config", "-", "--adapter", "caddyfile"]
    else:
        docker = shutil.which("docker")
        try:
            available = (
                docker is not None
                and subprocess.run(  # noqa: S603 - discovered CLI, fixed read-only probe
                    [docker, "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            available = False
        if not available:
            if os.environ.get("CI", "").lower() == "true":
                pytest.fail("CI requires Caddy or Docker for real edge-log adaptation proof")
            pytest.skip("Caddy and Docker daemon unavailable; live adaptation is a separate proof")
        images = (ROOT / "infra/vps-foundation/config/release/foundation-images.env").read_text(
            encoding="utf-8"
        )
        image = re.search(r"^CADDY_IMAGE=(caddy@sha256:[0-9a-f]{64})$", images, re.MULTILINE)
        assert image, "Use only the reviewed digest-pinned foundation Caddy image"
        command = [
            docker,
            "run",
            "--rm",
            "--interactive",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "65534:65534",
            "--memory",
            "128m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "64",
            "--log-driver",
            "none",
            image[1],
            "caddy",
            "adapt",
            "--config",
            "-",
            "--adapter",
            "caddyfile",
        ]
    result = subprocess.run(  # noqa: S603 - fixed parser; stdin source, no server/listener or mounted files
        command,
        input=CADDYFILE,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, "Caddy could not adapt the checked-in edge configuration"
    return json.loads(result.stdout)


def _require_credential_filter(logger: dict) -> None:
    encoder = logger["encoder"]
    assert encoder["format"] == "filter"
    assert encoder["wrap"]["format"] == "json"
    query = encoder["fields"]["request>uri"]
    assert query["filter"] == "query"
    assert len(query["actions"]) == len(LOG_CREDENTIAL_QUERY_KEYS)
    assert {action["parameter"] for action in query["actions"]} == LOG_CREDENTIAL_QUERY_KEYS
    assert all(
        action["type"] == "replace" and action["value"] == "REDACTED" for action in query["actions"]
    )


def _require_all_caddy_request_logs_redacted(config: dict) -> None:
    logs = config["logging"]["logs"]
    runtime = logs["default"]
    _require_credential_filter(runtime)
    # The default keeps HTTP error logs; access has its separate stdout sink.
    assert not runtime.get("include")
    assert runtime.get("writer", {}).get("output", "stderr") == "stderr"
    access_logs = {name: log for name, log in logs.items() if name != "default"}
    assert len(access_logs) == 1
    access_name, access = next(iter(access_logs.items()))
    assert runtime["exclude"] == [f"http.log.access.{access_name}"]
    assert access["include"] == [f"http.log.access.{access_name}"]
    assert not access.get("exclude")
    assert access["writer"]["output"] == "stdout"
    _require_credential_filter(access)
    servers = config["apps"]["http"]["servers"]
    assert len(servers) == 1
    assert next(iter(servers.values()))["logs"]["default_logger_name"] == access_name


def test_real_caddy_adaptation_redacts_access_and_runtime_error_destinations(
    adapted_foundation_caddy_config: dict,
) -> None:
    _require_all_caddy_request_logs_redacted(adapted_foundation_caddy_config)


@pytest.mark.parametrize(
    "mutation", ["runtime-unfiltered", "access-token-missing", "error-excluded"]
)
def test_adapted_log_assertions_reject_incomplete_redaction(
    adapted_foundation_caddy_config: dict,
    mutation: str,
) -> None:
    candidate = copy.deepcopy(adapted_foundation_caddy_config)
    logs = candidate["logging"]["logs"]
    if mutation == "runtime-unfiltered":
        del logs["default"]["encoder"]
    elif mutation == "access-token-missing":
        access = next(log for name, log in logs.items() if name != "default")
        actions = access["encoder"]["fields"]["request>uri"]["actions"]
        actions[:] = [action for action in actions if action["parameter"] != "token"]
    else:
        logs["default"]["exclude"].append("http.log.error")
    with pytest.raises((AssertionError, KeyError)):
        _require_all_caddy_request_logs_redacted(candidate)


def test_release_fails_closed_on_identity_and_database_secrets() -> None:
    required_markers = (
        "AC_RELEASE_ID:?",
        "AC_DATABASE_URL:?",
        "AC_DATABASE_MIGRATOR_URL:?",
        "AC_SESSION_TOKEN_PEPPER:?",
        "AC_OAUTH_TRANSACTION_SECRET:?",
        "AC_EMAIL_CHALLENGE_SECRET:?",
        "AC_GOOGLE_OAUTH_CLIENT_ID:?",
        "AC_GOOGLE_OAUTH_CLIENT_SECRET:?",
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
    assert "AC_PUBLIC_LEARNER_TENANT_ID:-" in COMPOSE
    assert "AC_OPERATIONS_TENANT_ID:-" in COMPOSE
    assert "before external side effects are released" in (
        ROOT / "packages" / "python" / "ac_platform" / "application" / "settings.py"
    ).read_text(encoding="utf-8")
    assert COMPOSE.count("AC_EMAIL_PROVIDER: ${AC_EMAIL_PROVIDER:-fake}") == 1
    assert COMPOSE.count("AC_RESEND_API_KEY: ${AC_RESEND_API_KEY:-}") == 1
    assert COMPOSE.count("AC_RESEND_FROM: ${AC_RESEND_FROM:-}") == 1
    assert "RESEND_API_KEY:" not in COMPOSE.replace("AC_RESEND_API_KEY:", "")
    shared_environment = COMPOSE.split(
        "x-application-environment: &application-environment", maxsplit=1
    )[1].split("x-migration-environment: &migration-environment", maxsplit=1)[0]
    for worker_only_name in ("AC_EMAIL_PROVIDER", "AC_RESEND_API_KEY", "AC_RESEND_FROM"):
        assert worker_only_name not in shared_environment
    assert len(re.findall(r"^\s+AC_DATABASE_MIGRATOR_URL:", COMPOSE, re.MULTILINE)) == 1
    assert "x-migration-environment: &migration-environment" in COMPOSE
    assert "migrate:\n" in COMPOSE
    assert "<<: *migration-environment" in COMPOSE
    assert "-u AC_TRUSTED_PROXY_ADDRESSES" in INSTALLER
    assert "-u AC_EMAIL_CHALLENGE_SECRET" in INSTALLER
    assert "-u AC_OPERATIONS_TENANT_ID" in INSTALLER


def test_deployment_oauth_documentation_matches_mandatory_compose_contract() -> None:
    for document in (APPLICATION_README, APPLICATION_SECRETS):
        assert "Google OAuth is mandatory" in document
        assert "AC_GOOGLE_OAUTH_CLIENT_ID" in document
        assert "AC_GOOGLE_OAUTH_CLIENT_SECRET" in document

    assert "omit both and leave Google login disabled" not in APPLICATION_SECRETS
    assert "Google OAuth remains fail-closed" not in APPLICATION_README
    assert "rejects disabled or custom injected providers" in APPLICATION_README
    for document in (APPLICATION_README, APPLICATION_SECRETS):
        normalized_document = " ".join(document.split())
        assert (
            "real Google login/callback remain deployment-time operational evidence"
            in normalized_document
        )


@pytest.mark.parametrize(
    "client_id, client_secret",
    [
        (None, None),
        (None, "fixture-client-secret"),
        ("", "fixture-client-secret"),
        (" \t\n", "fixture-client-secret"),
        ("123.apps.googleusercontent.com", None),
        ("123.apps.googleusercontent.com", ""),
        ("123.apps.googleusercontent.com", " \t\r\n"),
        ("123.apps.googleusercontent.com", "\u2003"),
    ],
)
def test_oauth_secret_preflight_rejects_missing_or_whitespace_values_without_leaking(
    client_id: str | None,
    client_secret: str | None,
) -> None:
    environment = os.environ.copy()
    environment.pop("AC_GOOGLE_OAUTH_CLIENT_ID", None)
    environment.pop("AC_GOOGLE_OAUTH_CLIENT_SECRET", None)
    if client_id is not None:
        environment["AC_GOOGLE_OAUTH_CLIENT_ID"] = client_id
    if client_secret is not None:
        environment["AC_GOOGLE_OAUTH_CLIENT_SECRET"] = client_secret

    result = subprocess.run(  # noqa: S603 - checked repository script and interpreter
        [sys.executable, str(OAUTH_SECRET_PREFLIGHT)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    for value in (client_id, client_secret):
        if value and value.strip():
            assert value not in output


def test_oauth_secret_preflight_accepts_both_values_without_printing_them() -> None:
    environment = os.environ.copy()
    client_id = "123.apps.googleusercontent.com"
    client_secret = "fixture-client-secret"  # noqa: S105
    environment["AC_GOOGLE_OAUTH_CLIENT_ID"] = client_id
    environment["AC_GOOGLE_OAUTH_CLIENT_SECRET"] = client_secret

    result = subprocess.run(  # noqa: S603 - checked repository script and interpreter
        [sys.executable, str(OAUTH_SECRET_PREFLIGHT)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert client_id not in output
    assert client_secret not in output


def test_oauth_secret_preflight_runs_before_image_loading_and_compose_mutation() -> None:
    preflight = 'python3 "$release_dir/scripts/validate-google-oauth-secrets.py"'
    image_load = 'gzip --decompress --stdout "$image_bundle_dir/application-images.tar.gz"'
    compose_config = 'compose_for "$release_dir" config --quiet'
    mutation_start = "mutation_started=1"
    secret_wrapper = INSTALLER.split("with_release_secrets() {", maxsplit=1)[1].split(
        "\n}", maxsplit=1
    )[0]

    assert INSTALLER.index(preflight) < INSTALLER.index(image_load)
    assert INSTALLER.index(preflight) < INSTALLER.index(compose_config)
    assert INSTALLER.index(preflight) < INSTALLER.index(mutation_start)
    assert "-u AC_GOOGLE_OAUTH_CLIENT_ID" in secret_wrapper
    assert "-u AC_GOOGLE_OAUTH_CLIENT_SECRET" in secret_wrapper
    assert "-u AC_PUBLIC_LEARNER_TENANT_ID" in secret_wrapper
    assert "-u AC_OPERATIONS_TENANT_ID" in secret_wrapper


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


def test_rate_limit_proxy_boundary_uses_one_deterministic_edge_address() -> None:
    assert "ipv4_address: 172.18.0.2" in FOUNDATION_COMPOSE
    assert "--subnet 172.18.0.0/16" in FOUNDATION_BOOTSTRAP
    assert "--gateway 172.18.0.1" in FOUNDATION_BOOTSTRAP
    assert "Existing ac_edge network does not use the reviewed" in FOUNDATION_BOOTSTRAP
    assert "edge router uses exact trusted proxy address" in FOUNDATION_VALIDATOR


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


def test_api_and_admin_adapter_use_canonical_trusted_internal_dns() -> None:
    api_service = COMPOSE.split("\n  api:\n", maxsplit=1)[1].split("\n  worker:\n", maxsplit=1)[0]
    admin_service = COMPOSE.split("\n  admin-web:\n", maxsplit=1)[1].split(
        "\nnetworks:\n", maxsplit=1
    )[0]
    internal_api_host = "${AC_INTERNAL_API_HOST:?AC_INTERNAL_API_HOST is required}"

    assert "http://127.0.0.1:8000/health/ready" in COMPOSE
    assert "headers={'Host': os.environ['AC_API_HOST']}" in COMPOSE
    assert f"app:\n        aliases:\n          - {internal_api_host}" in api_service
    assert f'AC_INTERNAL_API_URL: "http://{internal_api_host}:8000"' in admin_service
    assert f"AC_INTERNAL_API_HOST: {internal_api_host}" in admin_service
    assert "AC_INTERNAL_API_APPROVED_ORIGINS" not in COMPOSE


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
    assert "AC_TRUSTED_PROXY_ADDRESSES=172.18.0.2" in staging
    assert "AC_TRUSTED_PROXY_ADDRESSES=172.18.0.2" in production
    assert "AC_EDGE_API_ALIAS=ac-staging-api" in staging
    assert "AC_EDGE_API_ALIAS=ac-production-api" in production
    assert ".staging.authorityclosers.com" not in staging
    assert "AC_EXTERNAL_SIDE_EFFECTS_HOLD=false" in staging
    assert "AC_EMAIL_PROVIDER=resend" in staging
    assert "AC_EXTERNAL_SIDE_EFFECTS_HOLD=true" in production
    assert "AC_EMAIL_PROVIDER=fake" in production
    assert "* text=auto eol=lf" in GIT_ATTRIBUTES
    assert "Released environment profile must use canonical LF line endings" in INSTALLER


def test_installer_reports_the_reviewed_profile_policy_without_secrets() -> None:
    policy_start = INSTALLER.index('external_side_effects_hold="')
    policy_end = INSTALLER.index("with_release_secrets() {", policy_start)
    policy = INSTALLER[policy_start:policy_end]
    final_status = INSTALLER[INSTALLER.index("printf 'PASS  ") :]

    assert "true) external_side_effects_status='held'" in policy
    assert "false) external_side_effects_status='released'" in policy
    assert "fake|resend)" in policy
    assert "with held external side effects" not in INSTALLER
    assert "external side effects: %s; email provider: %s" in final_status
    for secret_name in (
        "AC_RESEND_API_KEY",
        "AC_RESEND_FROM",
        "AC_GOOGLE_OAUTH_CLIENT_SECRET",
    ):
        assert secret_name not in final_status
    for compose_control_name in (
        "COMPOSE_PROJECT_NAME",
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "COMPOSE_PATH_SEPARATOR",
        "COMPOSE_ENV_FILES",
        "COMPOSE_DISABLE_ENV_FILE",
    ):
        assert f"-u {compose_control_name}" in INSTALLER
    assert '--project-name "$compose_project"' in INSTALLER

    # Policy classification comes from the exact release profile before any
    # Docker command or database/service mutation is started.
    assert INSTALLER.index(
        'profile_file="$release_dir/environments/$target_environment.env"'
    ) < INSTALLER.index("docker load")
    assert INSTALLER.index('external_side_effects_hold="$(profile_value') < INSTALLER.index(
        "mutation_started=1"
    )


@pytest.mark.parametrize(
    ("target_environment", "expected_status"),
    (("staging", "released,resend\n"), ("production", "held,fake\n")),
)
def test_installer_profile_parser_reports_effective_profile_policy(
    tmp_path: Path,
    target_environment: str,
    expected_status: str,
) -> None:
    profile = (APPLICATION / "environments" / f"{target_environment}.env").read_bytes()

    result = _run_profile_parser(tmp_path, profile, target_environment=target_environment)

    assert result.returncode == 0, result.stderr
    assert result.stdout == expected_status


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        (lambda profile: profile.replace(b"AC_EMAIL_PROVIDER=resend\n", b""), "missing"),
        (lambda profile: profile + b"not-an-assignment\n", "malformed assignment"),
        (
            lambda profile: profile.replace(
                b"AC_EMAIL_PROVIDER=resend\n", b"AC_EMAIL_PROVIDER=resend with-space\n"
            ),
            "empty or unsafe assignment",
        ),
        (lambda profile: profile + b"AC_EMAIL_PROVIDER=fake\n", "duplicate assignment"),
        (lambda profile: profile + b"AC_EMAIL_PROVIDER=\n", "duplicate assignment"),
        (
            lambda profile: profile.replace(b"AC_EMAIL_PROVIDER=resend\n", b"AC_EMAIL_PROVIDER=\n"),
            "empty or unsafe assignment",
        ),
        (
            lambda profile: profile.replace(
                b"AC_EXTERNAL_SIDE_EFFECTS_HOLD=false\n",
                b"AC_EXTERNAL_SIDE_EFFECTS_HOLD=maybe\n",
            ),
            "unexpected value for AC_EXTERNAL_SIDE_EFFECTS_HOLD",
        ),
        (
            lambda profile: profile.replace(
                b"AC_EMAIL_PROVIDER=resend\n", b"AC_EMAIL_PROVIDER=smtp\n"
            ),
            "unexpected value for AC_EMAIL_PROVIDER",
        ),
        (
            lambda profile: profile + b"AC_EXTERNAL_SIDE_EFFECTS_HOLD=\n",
            "duplicate assignment",
        ),
        (
            lambda profile: profile.replace(
                b"AC_COMPOSE_PROJECT=ac-application-staging\n",
                b"AC_COMPOSE_PROJECT=ac-application-production\n",
            ),
            "unexpected value for AC_COMPOSE_PROJECT",
        ),
        (
            lambda profile: profile.replace(
                b"AC_EDGE_LEARNER_ALIAS=ac-staging-learner\n",
                b"AC_EDGE_LEARNER_ALIAS=ac-production-learner\n",
            ),
            "unexpected value for AC_EDGE_LEARNER_ALIAS",
        ),
        (
            lambda profile: profile.replace(
                b"AC_PUBLIC_APP_URL=https://staging.authorityclosers.com\n",
                b"AC_PUBLIC_APP_URL=https://app.authorityclosers.com\n",
            ),
            "unexpected value for AC_PUBLIC_APP_URL",
        ),
        (lambda profile: profile + b"AC_RESEND_API_KEY=secret-like-value\n", "unexpected key"),
    ),
)
def test_installer_profile_parser_rejects_bad_profiles_before_mutation(
    tmp_path: Path,
    mutation: Callable[[bytes], bytes],
    expected_error: str,
) -> None:
    profile = (APPLICATION / "environments" / "staging.env").read_bytes()
    mutated_profile = mutation(profile)

    result = _run_profile_parser(tmp_path, mutated_profile)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert "resend with-space" not in result.stderr


def test_installer_profile_parser_rejects_crlf_profiles(tmp_path: Path) -> None:
    profile = (APPLICATION / "environments" / "staging.env").read_bytes()
    crlf_profile = profile.replace(b"\n", b"\r\n")

    result = _run_profile_parser(tmp_path, crlf_profile)

    assert result.returncode != 0
    assert "canonical LF line endings" in result.stderr


def test_compose_for_uses_profile_policy_over_ambient_environment(tmp_path: Path) -> None:
    result = _run_compose_for_probe(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "name: ac-application-staging" in result.stdout
    assert 'hold: "false"' in result.stdout
    assert "provider: resend" in result.stdout


def test_release_is_built_off_host_and_installed_with_backup_and_rollback() -> None:
    assert "workflow_dispatch:" in WORKFLOW
    assert "packages: write" in WORKFLOW
    assert WORKFLOW.count("load: true") == 3
    assert "Refusing to overwrite immutable release tag" in WORKFLOW
    assert "release-images.env" in WORKFLOW
    assert 'tar --extract --to-stdout --file "$transport_tar" index.json' in WORKFLOW
    assert "transport_digest_for" in WORKFLOW
    assert "verify_transport_config" in WORKFLOW
    assert "AC_RELEASE_ID=${{ github.sha }}" in WORKFLOW
    assert "API image release marker does not match the workflow commit" in WORKFLOW
    assert "AC_MIGRATION_HEAD=%s" in WORKFLOW and "migration_head" in WORKFLOW
    assert "AC_MIGRATION_HEAD" in INSTALLER
    assert "OCI transport manifest does not reference the reviewed image config" in WORKFLOW
    assert "printf 'AC_API_IMAGE=%s\\n' \"$api_transport_digest\"" in WORKFLOW
    assert "printf 'AC_API_TRANSPORT_DIGEST=%s\\n' \"$api_transport_digest\"" in WORKFLOW
    assert 'verify-bundle "$artifact_dir" "$GITHUB_SHA"' in WORKFLOW
    assert "AC_API_TRANSPORT_DIGEST" in RELEASE_INPUT_PREPARER
    assert "Application deployment requires exact local OCI manifest IDs" in INSTALLER
    assert "Application deployment requires exact OCI transport manifest digests" in INSTALLER
    assert "Loaded API image release marker does not match the release ID" in INSTALLER
    assert (
        'cmp --silent "$api_release_marker_file" "$expected_api_release_marker_file"' in INSTALLER
    )
    assert "Loaded API image migration head does not match the reviewed bundle" in INSTALLER
    assert INSTALLER.index("Loaded API image migration head") < INSTALLER.index(
        "mutation_started=1"
    )
    assert "max_artifact_bytes=450000000" in WORKFLOW
    assert "max_artifact_pool_bytes=450000000" in WORKFLOW
    assert "refusing upload above" in WORKFLOW
    assert "group: application-release-packaging" in WORKFLOW
    assert "actions: write" in WORKFLOW
    assert 'test("^ac-application-[0-9a-f]{40}$")' in WORKFLOW
    assert "gh api --method DELETE" in WORKFLOW
    assert "projected_artifact_pool_bytes" in WORKFLOW
    assert WORKFLOW.index('verify-bundle "$artifact_dir" "$GITHUB_SHA"') < WORKFLOW.index(
        "Admit release artifact under the pooled ceiling"
    )
    upload_index = WORKFLOW.index("Upload reviewed release bundle")
    reclaim_index = WORKFLOW.index("Reclaim superseded release artifacts after verified upload")
    assert WORKFLOW.index("projected_artifact_pool_bytes") < upload_index
    assert upload_index < reclaim_index
    assert upload_index < WORKFLOW.index("gh api --method DELETE")
    assert "Uploaded release artifact could not be proven for this workflow run" in WORKFLOW
    assert "Final release artifact pool could not be proven" in WORKFLOW
    assert "retention-days: 1" in WORKFLOW
    assert "Prove staging seed PostgreSQL serialization" in WORKFLOW
    assert 'AC_REQUIRE_STAGING_SEED_POSTGRES_TEST: "1"' in WORKFLOW
    assert "pytest tests/integration/test_staging_seed_postgresql.py" in WORKFLOW
    assert 'AC_REQUIRE_RESTORE_INPUT_DOCKER_TEST: "1"' in WORKFLOW
    assert "docker build" not in INSTALLER
    assert "docker load" in INSTALLER
    assert "pg_dump" in INSTALLER and "--create" in INSTALLER
    assert "pg_restore" in INSTALLER and "--clean" in INSTALLER
    assert "alembic downgrade" not in INSTALLER
    assert "Alembic revisions are forward-only" in APPLICATION_README
    assert "installer-created pre-migration database backup" in APPLICATION_README
    assert "ROLLBACK" in INSTALLER
    assert "flock --exclusive --nonblock 9" in INSTALLER
    assert "Another application deployment is already active." in INSTALLER
    assert "trap 'exit 129' HUP" in INSTALLER
    assert "trap 'exit 130' INT" in INSTALLER
    assert "trap 'exit 143' TERM" in INSTALLER
    assert "trap '' HUP INT TERM" in INSTALLER
    assert "restore_current_link" in INSTALLER
    assert "current_switch_armed=1" in INSTALLER
    assert 'readlink -f "$current_link"' in INSTALLER
    assert 'rm -- "$current_link"' in INSTALLER
    assert 'mktemp "$evidence_root/.deployment-${release_id}.XXXXXX"' in INSTALLER
    assert 'mv --no-target-directory "$evidence_tmp" "$evidence_file"' in INSTALLER
    assert "AC_EXTERNAL_SIDE_EFFECTS_HOLD" in COMPOSE
    assert "/usr/local/sbin/ac-infisical-run" in INSTALLER
    assert 'find "$stage_dir/postgres/init" -type d -exec chmod 0755' in INSTALLER
    assert 'find "$stage_dir/postgres/init" -type f -exec chmod 0644' in INSTALLER
    postgres_bootstrap = (APPLICATION / "postgres" / "init" / "001-roles.sh").read_text(
        encoding="utf-8"
    )
    assert "GRANT USAGE, SELECT ON SEQUENCES TO ac_backup" in postgres_bootstrap


def test_api_image_bakes_a_root_owned_read_only_release_marker() -> None:
    assert "ARG AC_RELEASE_ID" in PYTHON_DOCKERFILE
    assert "^[0-9a-f]{40}$" in PYTHON_DOCKERFILE
    assert "printf '%s\\n' \"$AC_RELEASE_ID\" > /app/.ac-release-id" in PYTHON_DOCKERFILE
    assert "--chmod=0444 /app/.ac-release-id /app/.ac-release-id" in PYTHON_DOCKERFILE
    assert PYTHON_DOCKERFILE.index("/app/.ac-release-id") < PYTHON_DOCKERFILE.index("USER ac")


def test_release_bundle_uses_verified_transport_manifests_as_runtime_ids() -> None:
    assert 'verify_transport_config "$api_transport_digest" "$api_id"' in WORKFLOW
    for component in ("api", "learner", "admin"):
        assert (
            f"printf 'AC_{component.upper()}_IMAGE=%s\\n' \"${component}_transport_digest\""
        ) in WORKFLOW
        assert (
            f"printf 'AC_{component.upper()}_TRANSPORT_DIGEST=%s\\n' "
            f'"${component}_transport_digest"'
        ) in WORKFLOW

    image_load = 'gzip --decompress --stdout "$image_bundle_dir/application-images.tar.gz"'
    loaded_id_check = "docker image inspect --format '{{.Id}}' \"$image_id\""
    marker_check = '--entrypoint /bin/sh "$AC_API_IMAGE"'
    migration_check = '--entrypoint alembic "$AC_API_IMAGE" heads'
    mutation_start = "mutation_started=1"
    assert INSTALLER.index(image_load) < INSTALLER.index(loaded_id_check)
    assert INSTALLER.index(loaded_id_check) < INSTALLER.index(marker_check)
    assert INSTALLER.index(marker_check) < INSTALLER.index(migration_check)
    assert INSTALLER.index(migration_check) < INSTALLER.index(mutation_start)


def test_infisical_runner_accepts_only_named_environment_and_safe_path() -> None:
    assert "dev|staging|prod" in INFISICAL_RUNNER
    assert 'secret_path="${AC_INFISICAL_PATH:-/}"' in INFISICAL_RUNNER
    assert '--env="$secret_environment"' in INFISICAL_RUNNER
    assert '--path="$secret_path"' in INFISICAL_RUNNER
