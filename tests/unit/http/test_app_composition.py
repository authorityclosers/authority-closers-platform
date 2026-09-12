from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import ac_platform.http.app as app_module
from ac_platform.application.settings import Settings
from ac_platform.http.app import create_app
from ac_platform.http.identity_provider import DisabledIdentityProvider, OAuthIdentityProvider
from ac_platform.media.runtime import create_media_runtime


def _deployment_settings(environment: str) -> Settings:
    origins = (
        {
            "public_app_url": "https://app.authorityclosers.com",
            "admin_app_url": "https://admin.authorityclosers.com",
            "api_url": "https://api.authorityclosers.com",
        }
        if environment == "production"
        else {
            "public_app_url": "https://staging.authorityclosers.com",
            "admin_app_url": "https://admin-staging.authorityclosers.com",
            "api_url": "https://api-staging.authorityclosers.com",
        }
    )
    return Settings(
        environment=environment,  # type: ignore[arg-type]
        release_id="a" * 40,
        database_url=(
            "postgresql+psycopg://ac_runtime:deployment-runtime-password@postgres/ac_platform"
        ),
        database_migrator_url=(
            "postgresql+psycopg://ac_migrator:deployment-migrator-password@postgres/ac_platform"
        ),
        session_token_pepper="deployment-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="deployment-oauth-secret-that-is-long-enough",  # noqa: S106
        email_challenge_secret="deployment-email-challenge-secret-that-is-long-enough",  # noqa: S106
        google_oauth_client_id="123.apps.googleusercontent.com",
        google_oauth_client_secret="test-google-client-secret",  # noqa: S106
        trusted_proxy_addresses="172.18.0.2",
        internal_api_host=(
            "api.production.ac.internal.invalid"
            if environment == "production"
            else "api.staging.ac.internal.invalid"
        ),
        session_cookie_name="__Host-ac_session",
        oauth_transaction_cookie_name="__Host-ac_oauth_transaction",
        operations_tenant_id="33333333-3333-4333-8333-333333333333",
        **origins,  # type: ignore[arg-type]
    )


def test_shipped_application_mounts_g1_command_and_query_routes() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/certificates/{certificate_id}" in paths
    assert "/v1/admin/program-versions/{program_version_id}/publish" in paths
    assert "/v1/admin/studio/readiness" in paths
    assert "/v1/admin/studio/programs" in paths
    assert "/v1/admin/studio/programs/{program_id}" in paths
    assert "/v1/admin/corrections" in paths
    assert "/v1/admin/enrollment-grants" in paths
    assert "/v1/admin/jobs/{job_id}/retry" in paths
    assert "/v1/admin/recovery/reconcile" in paths
    assert "/v1/admin/learners/lookup" in paths
    assert "/v1/admin/learners/{person_id}/diagnosis" in paths
    assert "/v1/media/uploads" in paths
    assert "/v1/profile/avatar" in paths
    assert "/v1/media/{asset_id}/playback-token" in paths
    assert "/internal/v1/providers/{provider}/webhooks" not in paths
    assert "/v1/learning/home" in paths
    assert "/v1/learning/calendar" in paths
    assert "/v1/analytics/taxonomy" in paths
    assert "/v1/analytics/events" not in paths
    assert "/v1/telemetry/events" in paths

    # Provider callbacks stay fail-closed until a signed adapter is explicitly
    # registered by application composition.
    assert "/internal/v1/providers/video/webhooks" not in paths
    assert "/internal/v1/media/providers/{provider}/webhooks" not in paths


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployment_composition_omits_unconfigured_playback_routes(
    environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "settings", _deployment_settings(environment))

    paths = create_app().openapi()["paths"]

    assert "/v1/activities/{activity_id}/playback/start" not in paths
    assert "/v1/activities/{activity_id}/playback/heartbeat" not in paths
    assert "/v1/activities/{activity_id}/playback/finish" not in paths


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployment_composition_rejects_injected_unverified_media_runtime(
    environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "settings", _deployment_settings(environment))
    injected = create_media_runtime(Settings(environment="test"))

    with pytest.raises(RuntimeError, match="injected media runtimes"):
        create_app(media_runtime=injected)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_non_local_composition_rejects_enabled_media_settings(
    environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        _deployment_settings(environment).model_copy(update={"media_provider_enabled": True}),
    )

    with pytest.raises(RuntimeError, match="enabled media provider settings"):
        create_app()


def test_public_api_documentation_is_available_outside_deployments() -> None:
    application = create_app()

    assert application.docs_url == "/docs"
    assert application.openapi_url == "/openapi.json"


def test_staging_and_production_disable_public_api_documentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for environment in ("staging", "production"):
        monkeypatch.setattr(app_module, "settings", _deployment_settings(environment))

        application = create_app()

        assert application.docs_url is None
        assert application.openapi_url is None


def test_deployment_composition_rejects_missing_google_oauth_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment_settings = _deployment_settings("staging").model_copy(
        update={
            "google_oauth_client_id": "   ",
            "google_oauth_client_secret": SecretStr("   "),
        }
    )
    monkeypatch.setattr(app_module, "settings", deployment_settings)

    with pytest.raises(RuntimeError, match="Google OAuth pair"):
        create_app()


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    "provider",
    [
        DisabledIdentityProvider(),
        cast(OAuthIdentityProvider, object()),
    ],
    ids=["disabled", "custom"],
)
def test_deployment_composition_rejects_injected_identity_providers(
    environment: str,
    provider: OAuthIdentityProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "settings", _deployment_settings(environment))

    with pytest.raises(RuntimeError, match="rejects injected identity providers"):
        create_app(identity_provider=provider)


@pytest.mark.parametrize("environment", ["test", "development"])
def test_non_deployment_composition_preserves_identity_provider_injection(
    environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        Settings(environment=environment),  # type: ignore[arg-type]
    )

    application = create_app(identity_provider=DisabledIdentityProvider())

    assert application.docs_url == "/docs"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployment_constructs_google_provider_only_from_settings(
    environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment_settings = _deployment_settings(environment)
    observed: dict[str, str] = {}

    def create_provider(*, client_id: str, client_secret: str) -> OAuthIdentityProvider:
        observed.update(client_id=client_id, client_secret=client_secret)
        return cast(OAuthIdentityProvider, object())

    monkeypatch.setattr(app_module, "settings", deployment_settings)
    monkeypatch.setattr(app_module, "create_google_provider", create_provider)

    create_app()

    assert observed == {
        "client_id": deployment_settings.google_oauth_client_id,
        "client_secret": "test-google-client-secret",  # noqa: S105
    }


def test_deployment_composition_does_not_enable_cross_surface_browser_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment_settings = _deployment_settings("staging")
    monkeypatch.setattr(app_module, "settings", deployment_settings)

    application = create_app()

    assert all(
        middleware.cls.__name__ != "CORSMiddleware" for middleware in application.user_middleware
    )


def test_local_cors_allows_exact_quote_header_for_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "settings", Settings(environment="local"))
    with TestClient(create_app(identity_provider=DisabledIdentityProvider())) as client:
        response = client.options(
            "/v1/conversation/recordings/00000000-0000-4000-8000-000000000001/source",
            headers={
                "Origin": app_module.settings.allowed_origins[0],
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "Content-Type,X-Analysis-Quote",
            },
        )
    assert response.status_code == 200
    assert "x-analysis-quote" in response.headers["access-control-allow-headers"].lower()


def test_deployment_coach_host_is_trusted_but_restricted_before_identity_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "settings", _deployment_settings("staging"))
    with TestClient(create_app()) as client:
        allowed = client.get("/health/live", headers={"host": "coach-staging.authorityclosers.com"})
        identity = client.get("/v1/me", headers={"host": "coach-staging.authorityclosers.com"})
        denied = client.post(
            "/v1/admin/corrections",
            headers={
                "host": "coach-staging.authorityclosers.com",
                "x-forwarded-host": "admin-staging.authorityclosers.com",
            },
        )
        impostor = client.get(
            "/health/live", headers={"host": "coach-staging.authorityclosers.com.attacker.example"}
        )
    assert allowed.status_code == 200
    assert identity.status_code == 401
    assert denied.status_code == 403 and denied.json()["code"] == "coach_surface_route_denied"
    assert impostor.status_code == 400


@pytest.mark.parametrize(
    ("environment", "internal_api_host", "public_api_host"),
    [
        (
            "staging",
            "api.staging.ac.internal.invalid",
            "api-staging.authorityclosers.com",
        ),
        (
            "production",
            "api.production.ac.internal.invalid",
            "api.authorityclosers.com",
        ),
    ],
)
def test_deployment_trusted_host_accepts_only_canonical_public_and_internal_api_hosts(
    environment: str,
    internal_api_host: str,
    public_api_host: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "settings", _deployment_settings(environment))

    with TestClient(create_app()) as client:
        accepted_internal = client.get(
            "/health/live", headers={"host": f"{internal_api_host}:8000"}
        )
        accepted_public = client.get("/health/live", headers={"host": f"{public_api_host}:8000"})
        rejected = client.get(
            "/health/live",
            headers={"host": f"{internal_api_host}.attacker.example:8000"},
        )

    assert accepted_internal.status_code == 200
    assert accepted_public.status_code == 200
    assert rejected.status_code == 400
