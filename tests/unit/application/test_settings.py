from __future__ import annotations

import pytest
from pydantic import ValidationError

from ac_platform.application.settings import Settings


def _production_values() -> dict[str, str]:
    return {
        "release_id": "1" * 40,
        "database_url": (
            "postgresql+psycopg://ac_runtime:runtime-production-password@postgres/ac_platform"
        ),
        "database_migrator_url": (
            "postgresql+psycopg://ac_migrator:migrator-production-password@postgres/ac_platform"
        ),
        "public_app_url": "https://app.authorityclosers.com",
        "admin_app_url": "https://admin.authorityclosers.com",
        "api_url": "https://api.authorityclosers.com",
        "session_token_pepper": "production-session-pepper-that-is-long-enough",
        "oauth_transaction_secret": "production-oauth-secret-that-is-also-long-enough",
        "trusted_proxy_addresses": "172.18.0.2",
    }


def _staging_values() -> dict[str, str]:
    values = _production_values()
    values.update(
        {
            "public_app_url": "https://staging.authorityclosers.com",
            "admin_app_url": "https://admin-staging.authorityclosers.com",
            "api_url": "https://api-staging.authorityclosers.com",
        }
    )
    return values


@pytest.mark.parametrize(
    "overrides, expected_field",
    [
        ({}, "AC_SESSION_TOKEN_PEPPER"),
        (
            {"session_token_pepper": "production-session-pepper-that-is-long-enough"},
            "AC_OAUTH_TRANSACTION_SECRET",
        ),
    ],
)
def test_production_rejects_local_identity_material(
    overrides: dict[str, str], expected_field: str
) -> None:
    values = {
        **_production_values(),
        "session_token_pepper": "local-session-token-pepper-change-before-production",
        "oauth_transaction_secret": "local-oauth-transaction-secret-change-before-production",
        **overrides,
    }
    with pytest.raises(ValidationError, match=expected_field):
        Settings(environment="production", **values)  # type: ignore[arg-type]


def test_production_accepts_independent_non_default_identity_material() -> None:
    settings = Settings(environment="production", **_production_values())  # type: ignore[arg-type]

    assert settings.secure_cookies is True
    assert settings.session_token_pepper.get_secret_value() != (
        settings.oauth_transaction_secret.get_secret_value()
    )


def test_production_runtime_does_not_require_migration_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AC_DATABASE_MIGRATOR_URL", raising=False)
    values = _production_values()
    del values["database_migrator_url"]

    settings = Settings(environment="production", _env_file=None, **values)  # type: ignore[arg-type]

    assert settings.database_migrator_url is None


def test_staging_is_production_shaped_but_uses_isolated_origins() -> None:
    settings = Settings(environment="staging", **_staging_values())  # type: ignore[arg-type]

    assert settings.secure_cookies is True
    assert settings.allowed_hosts == [
        "admin-staging.authorityclosers.com",
        "api-staging.authorityclosers.com",
        "staging.authorityclosers.com",
    ]

    invalid = {**_staging_values(), "public_app_url": "https://app.authorityclosers.com"}
    with pytest.raises(ValidationError, match="AC_PUBLIC_APP_URL"):
        Settings(environment="staging", **invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field, invalid_value, expected_error",
    [
        ("release_id", "local-unreleased", "AC_RELEASE_ID"),
        (
            "database_url",
            "postgresql+psycopg://ac_runtime:local-runtime-only@localhost/ac_platform",
            "AC_DATABASE_URL",
        ),
        (
            "database_migrator_url",
            "postgresql+psycopg://ac_runtime:runtime-production-password@postgres/ac_platform",
            "AC_DATABASE_MIGRATOR_URL",
        ),
        ("public_app_url", "http://localhost:3000", "AC_PUBLIC_APP_URL"),
    ],
)
def test_production_rejects_local_release_database_and_origins(
    field: str, invalid_value: str, expected_error: str
) -> None:
    values = {**_production_values(), field: invalid_value}

    with pytest.raises(ValidationError, match=expected_error):
        Settings(environment="production", **values)  # type: ignore[arg-type]


def test_production_rejects_reused_identity_secret() -> None:
    values = _production_values()
    values["oauth_transaction_secret"] = values["session_token_pepper"]

    with pytest.raises(ValidationError, match="must be independent"):
        Settings(environment="production", **values)  # type: ignore[arg-type]


def test_google_oauth_credentials_are_all_or_nothing() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(
            environment="test",
            google_oauth_client_id="123.apps.googleusercontent.com",
        )


def test_google_oauth_web_client_pair_enables_provider_composition() -> None:
    settings = Settings(
        environment="test",
        google_oauth_client_id="123.apps.googleusercontent.com",
        google_oauth_client_secret="test-google-client-secret",  # noqa: S106
    )

    assert settings.google_oauth_configured is True


def test_deployment_requires_exact_trusted_proxy_addresses() -> None:
    values = _production_values()
    values["trusted_proxy_addresses"] = ""
    with pytest.raises(ValidationError, match="AC_TRUSTED_PROXY_ADDRESSES"):
        Settings(environment="production", **values)  # type: ignore[arg-type]

    values["trusted_proxy_addresses"] = "172.18.0.0/16"
    with pytest.raises(ValidationError, match="comma-separated exact IPs"):
        Settings(environment="production", **values)  # type: ignore[arg-type]


def test_trusted_proxy_addresses_are_normalized_and_deduplicated() -> None:
    values = _production_values()
    values["trusted_proxy_addresses"] = "172.18.0.2, 2001:db8::2,172.18.0.2"

    settings = Settings(environment="production", **values)  # type: ignore[arg-type]

    assert {str(value) for value in settings.rate_limit_trusted_proxy_addresses} == {
        "172.18.0.2",
        "2001:db8::2",
    }
