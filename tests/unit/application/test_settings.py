from __future__ import annotations

import pytest
from pydantic import AnyHttpUrl, ValidationError

from ac_platform.application.settings import Settings


def test_blank_optional_public_learner_tenant_is_unconfigured() -> None:
    settings = Settings(public_learner_tenant_id="", operations_tenant_id="")

    assert settings.public_learner_tenant_id is None
    assert settings.operations_tenant_id is None


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
        "internal_api_host": "api.production.ac.internal.invalid",
        "session_cookie_name": "__Host-ac_session",
        "oauth_transaction_cookie_name": "__Host-ac_oauth_transaction",
        "session_token_pepper": "production-session-pepper-that-is-long-enough",
        "oauth_transaction_secret": "production-oauth-secret-that-is-also-long-enough",
        "email_challenge_secret": "production-email-challenge-secret-that-is-long-enough",
        "google_oauth_client_id": "123.apps.googleusercontent.com",
        "google_oauth_client_secret": "production-google-client-secret",
        "trusted_proxy_addresses": "172.18.0.2",
        "operations_tenant_id": "10000000-0000-4000-8000-000000000001",
    }


def _staging_values() -> dict[str, str]:
    values = _production_values()
    values.update(
        {
            "public_app_url": "https://staging.authorityclosers.com",
            "admin_app_url": "https://admin-staging.authorityclosers.com",
            "api_url": "https://api-staging.authorityclosers.com",
            "internal_api_host": "api.staging.ac.internal.invalid",
        }
    )
    return values


_DEPLOYMENT_ORIGINS = {
    "staging": {
        "public_app_url": "https://staging.authorityclosers.com",
        "admin_app_url": "https://admin-staging.authorityclosers.com",
        "api_url": "https://api-staging.authorityclosers.com",
    },
    "production": {
        "public_app_url": "https://app.authorityclosers.com",
        "admin_app_url": "https://admin.authorityclosers.com",
        "api_url": "https://api.authorityclosers.com",
    },
}
_DEPLOYMENT_URL_ENV_FIELDS = {
    "public_app_url": "AC_PUBLIC_APP_URL",
    "admin_app_url": "AC_ADMIN_APP_URL",
    "api_url": "AC_API_URL",
}


def _deployment_values(environment: str) -> dict[str, str]:
    return _staging_values() if environment == "staging" else _production_values()


def _invalid_origin_values(origin: str) -> list[tuple[str, str]]:
    return [
        ("trailing-query-delimiter", f"{origin}?"),
        ("trailing-fragment-delimiter", f"{origin}#"),
        ("trailing-colon", f"{origin}:"),
        ("default-port", f"{origin}:443"),
        ("alternate-port", f"{origin}:8443"),
        ("username", origin.replace("https://", "https://user@", 1)),
        ("password", origin.replace("https://", "https://user:password@", 1)),
        ("query", f"{origin}?surface=learner"),
        ("fragment", f"{origin}#home"),
        ("non-root-path", f"{origin}/v1"),
        ("wrong-scheme", origin.replace("https://", "http://", 1)),
        ("wrong-host", origin.replace(".authorityclosers.com", ".example.com")),
        ("leading-whitespace", f" {origin}"),
        ("trailing-whitespace", f"{origin} "),
    ]


@pytest.mark.parametrize(
    "overrides, expected_field",
    [
        ({}, "AC_SESSION_TOKEN_PEPPER"),
        (
            {"session_token_pepper": "production-session-pepper-that-is-long-enough"},
            "AC_OAUTH_TRANSACTION_SECRET",
        ),
        (
            {
                "session_token_pepper": "production-session-pepper-that-is-long-enough",
                "oauth_transaction_secret": "production-oauth-secret-that-is-also-long-enough",
            },
            "AC_EMAIL_CHALLENGE_SECRET",
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
        "email_challenge_secret": "local-email-challenge-secret-change-before-production",
        **overrides,
    }
    with pytest.raises(ValidationError, match=expected_field):
        Settings(environment="production", **values)  # type: ignore[arg-type]


def test_production_accepts_independent_non_default_identity_material() -> None:
    settings = Settings(environment="production", **_production_values())  # type: ignore[arg-type]

    assert settings.secure_cookies is True
    assert settings.session_cookie_name == "__Host-ac_session"
    assert settings.oauth_transaction_cookie_name == "__Host-ac_oauth_transaction"
    assert settings.internal_api_host == "api.production.ac.internal.invalid"
    assert settings.operations_tenant_id is not None
    assert settings.session_token_pepper.get_secret_value() != (
        settings.oauth_transaction_secret.get_secret_value()
    )
    assert (
        len(
            {
                settings.session_token_pepper.get_secret_value(),
                settings.oauth_transaction_secret.get_secret_value(),
                settings.email_challenge_secret.get_secret_value(),
            }
        )
        == 3
    )


def test_production_runtime_does_not_require_migration_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AC_DATABASE_MIGRATOR_URL", raising=False)
    values = _production_values()
    del values["database_migrator_url"]

    settings = Settings(environment="production", _env_file=None, **values)  # type: ignore[arg-type]

    assert settings.database_migrator_url is None


def test_deployment_requires_an_exact_operations_control_tenant_before_release() -> None:
    values = _production_values()
    del values["operations_tenant_id"]
    values["external_side_effects_hold"] = False

    with pytest.raises(ValidationError, match="AC_OPERATIONS_TENANT_ID"):
        Settings(environment="production", _env_file=None, **values)  # type: ignore[arg-type]


def test_deployment_allows_empty_control_tenant_only_while_side_effects_are_held() -> None:
    values = _production_values()
    del values["operations_tenant_id"]

    settings = Settings(environment="production", _env_file=None, **values)  # type: ignore[arg-type]

    assert settings.external_side_effects_hold is True
    assert settings.operations_tenant_id is None


def test_staging_is_production_shaped_but_uses_isolated_origins() -> None:
    settings = Settings(environment="staging", **_staging_values())  # type: ignore[arg-type]

    assert settings.secure_cookies is True
    assert set(settings.allowed_hosts) == {
        "admin-staging.authorityclosers.com",
        "api.staging.ac.internal.invalid",
        "api-staging.authorityclosers.com",
        "staging.authorityclosers.com",
    }

    invalid = {**_staging_values(), "public_app_url": "https://app.authorityclosers.com"}
    with pytest.raises(ValidationError, match="AC_PUBLIC_APP_URL"):
        Settings(environment="staging", **invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "environment, field, case, url",
    [
        (environment, field, case, url)
        for environment, origins in _DEPLOYMENT_ORIGINS.items()
        for field, origin in origins.items()
        for case, url in _invalid_origin_values(origin)
    ],
)
def test_deployment_rejects_non_canonical_raw_origins(
    environment: str,
    field: str,
    case: str,
    url: str,
) -> None:
    del case
    values = {**_deployment_values(environment), field: url}

    with pytest.raises(ValidationError, match=_DEPLOYMENT_URL_ENV_FIELDS[field]):
        Settings(
            environment=environment,  # type: ignore[arg-type]
            _env_file=None,
            **values,
        )


@pytest.mark.parametrize(
    "environment, field, origin, raw_suffix",
    [
        (environment, field, origin, raw_suffix)
        for environment, origins in _DEPLOYMENT_ORIGINS.items()
        for field, origin in origins.items()
        for raw_suffix in ("", ":443")
    ],
)
def test_deployment_rejects_preparsed_origins(
    environment: str,
    field: str,
    origin: str,
    raw_suffix: str,
) -> None:
    values: dict[str, object] = _deployment_values(environment)
    values[field] = AnyHttpUrl(f"{origin}{raw_suffix}")

    with pytest.raises(ValidationError, match=_DEPLOYMENT_URL_ENV_FIELDS[field]):
        Settings(
            environment=environment,  # type: ignore[arg-type]
            _env_file=None,
            **values,
        )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployment_accepts_canonical_origins_with_root_slashes(environment: str) -> None:
    values = _deployment_values(environment)
    for field in _DEPLOYMENT_URL_ENV_FIELDS:
        values[field] = f"{values[field]}/"

    settings = Settings(
        environment=environment,  # type: ignore[arg-type]
        _env_file=None,
        **values,
    )

    assert str(settings.public_app_url).endswith("/")
    assert str(settings.admin_app_url).endswith("/")
    assert str(settings.api_url).endswith("/")


@pytest.mark.parametrize(
    ("environment", "invalid_host"),
    [
        ("staging", "api.production.ac.internal.invalid"),
        ("staging", "api-staging.authorityclosers.com"),
        ("staging", " api.staging.ac.internal.invalid"),
        ("production", "api.staging.ac.internal.invalid"),
        ("production", "api.authorityclosers.com"),
        ("production", "api.production.ac.internal.invalid."),
    ],
)
def test_deployment_rejects_noncanonical_internal_api_host(
    environment: str,
    invalid_host: str,
) -> None:
    values = {
        **_deployment_values(environment),
        "internal_api_host": invalid_host,
    }

    with pytest.raises(ValidationError, match="AC_INTERNAL_API_HOST"):
        Settings(
            environment=environment,  # type: ignore[arg-type]
            _env_file=None,
            **values,
        )


@pytest.mark.parametrize(
    ("field", "invalid_name", "expected_error"),
    [
        ("session_cookie_name", "ac_session", "AC_SESSION_COOKIE_NAME"),
        ("session_cookie_name", "__Secure-ac_session", "AC_SESSION_COOKIE_NAME"),
        (
            "oauth_transaction_cookie_name",
            "ac_oauth_transaction",
            "AC_OAUTH_TRANSACTION_COOKIE_NAME",
        ),
        (
            "oauth_transaction_cookie_name",
            "__Host-ac_oauth_transaction ",
            "AC_OAUTH_TRANSACTION_COOKIE_NAME",
        ),
    ],
)
def test_deployment_requires_exact_host_only_cookie_names(
    field: str,
    invalid_name: str,
    expected_error: str,
) -> None:
    values = {**_production_values(), field: invalid_name}

    with pytest.raises(ValidationError, match=expected_error):
        Settings(environment="production", _env_file=None, **values)  # type: ignore[arg-type]


def test_test_environment_keeps_developer_cookie_names() -> None:
    settings = Settings(environment="test", _env_file=None)

    assert settings.session_cookie_name == "ac_session"
    assert settings.oauth_transaction_cookie_name == "ac_oauth_transaction"
    assert settings.secure_cookies is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"google_oauth_client_id": "   ", "google_oauth_client_secret": "   "},
        {},
    ],
)
def test_deployment_requires_a_non_empty_google_oauth_pair(
    overrides: dict[str, str],
) -> None:
    values = {**_production_values(), **overrides}
    if not overrides:
        values.pop("google_oauth_client_id")
        values.pop("google_oauth_client_secret")

    with pytest.raises(ValidationError, match="AC_GOOGLE_OAUTH_CLIENT_ID"):
        Settings(environment="production", _env_file=None, **values)  # type: ignore[arg-type]


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


def test_production_rejects_email_challenge_secret_reused_as_session_pepper() -> None:
    values = _production_values()
    values["email_challenge_secret"] = values["session_token_pepper"]

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


def test_resend_provider_requires_secret_and_sender_as_one_fail_closed_pair() -> None:
    with pytest.raises(ValidationError, match="AC_RESEND_API_KEY"):
        Settings(environment="test", email_provider="resend")
    with pytest.raises(ValidationError, match="AC_RESEND_FROM"):
        Settings(
            environment="test",
            email_provider="resend",
            resend_api_key="re_test_only_key",  # noqa: S106
        )

    settings = Settings(
        environment="test",
        email_provider="resend",
        resend_api_key="re_test_only_key",  # noqa: S106
        resend_from="Authority Closers <learn@authorityclosers.test>",
    )

    assert settings.resend_api_key is not None
    assert settings.resend_api_key.get_secret_value() == "re_test_only_key"


@pytest.mark.parametrize("environment", ["test", "development"])
def test_blank_google_oauth_values_remain_unconfigured(environment: str) -> None:
    settings = Settings(
        environment=environment,  # type: ignore[arg-type]
        google_oauth_client_id="   ",
        google_oauth_client_secret="   ",  # noqa: S106
    )

    assert settings.google_oauth_configured is False


def test_deployment_requires_exact_trusted_proxy_addresses() -> None:
    values = _production_values()
    values["trusted_proxy_addresses"] = ""
    with pytest.raises(ValidationError, match="AC_TRUSTED_PROXY_ADDRESSES"):
        Settings(environment="production", **values)  # type: ignore[arg-type]

    values["trusted_proxy_addresses"] = "172.18.0.0/16"
    with pytest.raises(ValidationError, match="comma-separated exact IPs"):
        Settings(environment="production", **values)  # type: ignore[arg-type]

    values["trusted_proxy_addresses"] = "9.9.9.9"
    with pytest.raises(ValidationError, match="private or loopback"):
        Settings(environment="production", **values)  # type: ignore[arg-type]


def test_trusted_proxy_addresses_are_normalized_and_deduplicated() -> None:
    values = _production_values()
    values["trusted_proxy_addresses"] = "172.18.0.2, 2001:db8::2,172.18.0.2"

    settings = Settings(environment="production", **values)  # type: ignore[arg-type]

    assert {str(value) for value in settings.rate_limit_trusted_proxy_addresses} == {
        "172.18.0.2",
        "2001:db8::2",
    }
