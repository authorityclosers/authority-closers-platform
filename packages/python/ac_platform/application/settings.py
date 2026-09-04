from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from ac_platform.application.release_identity import require_baked_release_id

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
_DEPLOYMENT_INTERNAL_API_HOSTS = {
    "staging": "api.staging.ac.internal.invalid",
    "production": "api.production.ac.internal.invalid",
}
_DEPLOYMENT_COOKIE_NAMES = {
    "session_cookie_name": "__Host-ac_session",
    "oauth_transaction_cookie_name": "__Host-ac_oauth_transaction",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "test", "development", "staging", "production"] = "local"
    release_id: str = "local-unreleased"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://ac_runtime:local-runtime-only@127.0.0.1/ac_platform"
    database_migrator_url: str | None = None
    external_side_effects_hold: bool = True
    email_provider: Literal["fake", "resend"] = "fake"
    resend_api_key: SecretStr | None = None
    resend_from: str | None = None
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None
    public_app_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    admin_app_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3001")
    api_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    internal_api_host: str = "localhost"
    session_token_pepper: SecretStr = SecretStr(
        "local-session-token-pepper-change-before-production"
    )
    oauth_transaction_secret: SecretStr = SecretStr(
        "local-oauth-transaction-secret-change-before-production"
    )
    email_challenge_secret: SecretStr = SecretStr(
        "local-email-challenge-secret-change-before-production"
    )
    session_cookie_name: str = "ac_session"
    oauth_transaction_cookie_name: str = "ac_oauth_transaction"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    learner_consent_version: str | None = None
    public_learner_tenant_id: UUID | None = None
    operations_tenant_id: UUID | None = None
    trusted_proxy_addresses: str = ""

    # Media provider configuration is deliberately disabled by default.  The
    # The media boundary validates the complete storage/delivery contract as
    # input data only. References are evidence labels, not authorization; the
    # shipped staging/production composition rejects enabled media until a
    # later immutable external approval and safe transport exist. Keeping these
    # values here makes environment loading explicit without provider contact.
    media_provider_enabled: bool = False
    media_provider: Literal["unconfigured", "s3", "minio"] = "unconfigured"
    media_storage_endpoint: str | None = None
    media_storage_bucket: str | None = None
    media_storage_region: str | None = None
    media_storage_approved_endpoint_hosts: str = ""
    media_storage_access_key_id: str | None = None
    media_storage_secret_access_key: SecretStr | None = None
    media_delivery_origin: str | None = None
    media_cors_origins: str = ""
    media_governance_reference: str | None = None
    media_gap_reference: str | None = None
    media_upload_ttl_seconds: int = 900
    media_playback_ttl_seconds: int = 900
    media_max_upload_bytes: int = 512 * 1024 * 1024
    media_quota_window_seconds: int = 3600
    media_quota_bytes_per_actor: int = 2 * 1024 * 1024 * 1024
    media_quota_uploads_per_actor: int = 100
    media_max_renditions: int = 6
    media_max_processing_output_bytes: int = 4 * 1024 * 1024 * 1024
    media_max_processing_caption_bytes: int = 25 * 1024 * 1024
    media_allow_range_requests: bool = True
    # Explicitly opt-in test fixtures are separate from provider composition.
    # They are accepted only by the staging/test fixture seam and never by
    # production runtime composition.
    media_stress_fixtures_enabled: bool = False
    media_stress_fixtures_cache_root: str | None = None

    @field_validator("public_learner_tenant_id", "operations_tenant_id", mode="before")
    @classmethod
    def blank_optional_tenant_is_unconfigured(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="before")
    @classmethod
    def require_exact_raw_deployment_origins(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        environment = values.get("environment")
        if not isinstance(environment, str) or environment not in _DEPLOYMENT_ORIGINS:
            return values
        expected_origins = _DEPLOYMENT_ORIGINS[environment]
        for field, environment_field in _DEPLOYMENT_URL_ENV_FIELDS.items():
            raw_value = values.get(field)
            if raw_value is None:
                continue
            expected_origin = expected_origins[field]
            if not isinstance(raw_value, str) or raw_value not in {
                expected_origin,
                f"{expected_origin}/",
            }:
                raise ValueError(f"{environment_field} must be the canonical HTTPS origin")
        return values

    @model_validator(mode="after")
    def require_deployment_identity_secrets(self) -> Settings:
        if self.public_learner_tenant_id is not None and self.operations_tenant_id is None:
            raise ValueError(
                "AC_OPERATIONS_TENANT_ID is required when AC_PUBLIC_LEARNER_TENANT_ID is configured"
            )
        if (
            self.public_learner_tenant_id is not None
            and self.operations_tenant_id is not None
            and self.public_learner_tenant_id == self.operations_tenant_id
        ):
            raise ValueError(
                "AC_PUBLIC_LEARNER_TENANT_ID and AC_OPERATIONS_TENANT_ID must identify "
                "different tenants"
            )
        self._validate_media_stress_fixtures()
        self._validate_media_provider()
        if self.environment not in {"staging", "production"}:
            self._validate_google_oauth_pair()
            self._validate_email_provider()
            return self
        session_pepper = self.session_token_pepper.get_secret_value()
        transaction_secret = self.oauth_transaction_secret.get_secret_value()
        challenge_secret = self.email_challenge_secret.get_secret_value()
        if len(session_pepper.encode("utf-8")) < 32 or session_pepper.startswith("local-"):
            raise ValueError(
                "AC_SESSION_TOKEN_PEPPER must be a non-default value of at least 32 bytes"
            )
        if len(transaction_secret.encode("utf-8")) < 32 or transaction_secret.startswith("local-"):
            raise ValueError(
                "AC_OAUTH_TRANSACTION_SECRET must be a non-default value of at least 32 bytes"
            )
        if len(challenge_secret.encode("utf-8")) < 32 or challenge_secret.startswith("local-"):
            raise ValueError(
                "AC_EMAIL_CHALLENGE_SECRET must be a non-default value of at least 32 bytes"
            )
        if len({session_pepper, transaction_secret, challenge_secret}) != 3:
            raise ValueError("deployment identity secrets must be independent")
        if re.fullmatch(r"[0-9a-f]{40}", self.release_id) is None:
            raise ValueError("AC_RELEASE_ID must be the full lowercase Git commit SHA")
        expected_origins = _DEPLOYMENT_ORIGINS[self.environment]
        self._validate_deployment_url(
            self.public_app_url,
            field="AC_PUBLIC_APP_URL",
            expected_origin=expected_origins["public_app_url"],
        )
        self._validate_deployment_url(
            self.admin_app_url,
            field="AC_ADMIN_APP_URL",
            expected_origin=expected_origins["admin_app_url"],
        )
        self._validate_deployment_url(
            self.api_url,
            field="AC_API_URL",
            expected_origin=expected_origins["api_url"],
        )
        expected_internal_api_host = _DEPLOYMENT_INTERNAL_API_HOSTS[self.environment]
        if self.internal_api_host != expected_internal_api_host:
            raise ValueError(
                "AC_INTERNAL_API_HOST must be the environment's reserved internal hostname"
            )
        for field, expected_name in _DEPLOYMENT_COOKIE_NAMES.items():
            if getattr(self, field) != expected_name:
                environment_field = f"AC_{field.upper()}"
                raise ValueError(f"{environment_field} must use the exact __Host cookie name")
        if not self.secure_cookies:  # pragma: no cover - deployment environments imply Secure
            raise ValueError("deployment cookies must be Secure")
        self._validate_deployment_database(
            self.database_url,
            field="AC_DATABASE_URL",
            expected_user="ac_runtime",
        )
        if self.database_migrator_url is not None:
            self._validate_deployment_database(
                self.database_migrator_url,
                field="AC_DATABASE_MIGRATOR_URL",
                expected_user="ac_migrator",
            )
        if not self.rate_limit_trusted_proxy_addresses:
            raise ValueError("AC_TRUSTED_PROXY_ADDRESSES must contain at least one exact proxy IP")
        if self.operations_tenant_id is None and not self.external_side_effects_hold:
            raise ValueError(
                "AC_OPERATIONS_TENANT_ID must identify the exact operations control tenant "
                "before external side effects are released"
            )
        self._validate_google_oauth_pair(require_configured=True)
        self._validate_email_provider()
        return self

    def _validate_media_provider(self) -> None:
        """Validate media provider settings before runtime composition.

        The import is local to keep application settings independent from the
        media service module while still sharing one strict config contract.
        Disabled media remains inert and does not require any provider fields.
        """

        if not self.media_provider_enabled:
            return
        from ac_platform.media.config import MediaProviderConfig

        try:
            MediaProviderConfig.from_settings(self)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid media provider configuration: {error}") from error

    def _validate_media_stress_fixtures(self) -> None:
        """Keep local fixture opt-in outside production and normal local mode."""

        if self.media_stress_fixtures_enabled and self.environment == "production":
            raise ValueError("AC_MEDIA_STRESS_FIXTURES_ENABLED is forbidden in production")
        if self.media_stress_fixtures_enabled and self.environment not in {
            "test",
            "development",
            "staging",
        }:
            raise ValueError(
                "AC_MEDIA_STRESS_FIXTURES_ENABLED requires test, development, or staging"
            )
        if self.media_stress_fixtures_cache_root is not None:
            cache_root = self.media_stress_fixtures_cache_root.strip()
            if not cache_root:
                object.__setattr__(self, "media_stress_fixtures_cache_root", None)
            elif not self.media_stress_fixtures_enabled:
                raise ValueError(
                    "AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT requires explicit fixture opt-in"
                )
            else:
                path = Path(cache_root)
                if any(part == ".." for part in path.parts):
                    raise ValueError("AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT must not contain '..'")
                if "://" in cache_root or any(
                    ord(character) < 0x20 or ord(character) == 0x7F for character in cache_root
                ):
                    raise ValueError("AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT must be a local path")
                object.__setattr__(self, "media_stress_fixtures_cache_root", cache_root)
        elif self.media_stress_fixtures_enabled:
            raise ValueError("AC_MEDIA_STRESS_FIXTURES_ENABLED requires a configured cache root")

    def _validate_email_provider(self) -> None:
        if self.email_provider != "resend":
            return
        api_key = (
            "" if self.resend_api_key is None else self.resend_api_key.get_secret_value().strip()
        )
        sender = (self.resend_from or "").strip()
        if len(api_key) < 12:
            raise ValueError("AC_RESEND_API_KEY is required when AC_EMAIL_PROVIDER=resend")
        if not sender or "@" not in sender or "\r" in sender or "\n" in sender:
            raise ValueError("AC_RESEND_FROM is required when AC_EMAIL_PROVIDER=resend")

    @staticmethod
    def _validate_deployment_url(
        value: AnyHttpUrl,
        *,
        field: str,
        expected_origin: str,
    ) -> None:
        if str(value) != f"{expected_origin}/":
            raise ValueError(f"{field} must be the canonical HTTPS origin")

    @staticmethod
    def _validate_deployment_database(
        value: str,
        *,
        field: str,
        expected_user: str,
    ) -> None:
        try:
            database = make_url(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a valid SQLAlchemy PostgreSQL URL") from exc
        password = database.password or ""
        if (
            database.drivername != "postgresql+psycopg"
            or database.username != expected_user
            or database.database != "ac_platform"
            or database.host in {None, "localhost", "127.0.0.1", "::1"}
            or len(password) < 16
            or password.startswith("local-")
        ):
            raise ValueError(f"{field} must use the dedicated deployment PostgreSQL role")

    def _validate_google_oauth_pair(self, *, require_configured: bool = False) -> None:
        client_id = (self.google_oauth_client_id or "").strip()
        client_secret = (
            ""
            if self.google_oauth_client_secret is None
            else self.google_oauth_client_secret.get_secret_value().strip()
        )
        if bool(client_id) != bool(client_secret):
            raise ValueError(
                "AC_GOOGLE_OAUTH_CLIENT_ID and AC_GOOGLE_OAUTH_CLIENT_SECRET must be set together"
            )
        if require_configured and not (client_id and client_secret):
            raise ValueError(
                "AC_GOOGLE_OAUTH_CLIENT_ID and AC_GOOGLE_OAUTH_CLIENT_SECRET are required"
            )
        if client_id and (
            len(client_id) > 512 or not client_id.endswith(".apps.googleusercontent.com")
        ):
            raise ValueError("AC_GOOGLE_OAUTH_CLIENT_ID is not a Google web client ID")

    @property
    def google_oauth_configured(self) -> bool:
        client_id = (self.google_oauth_client_id or "").strip()
        client_secret = (
            ""
            if self.google_oauth_client_secret is None
            else self.google_oauth_client_secret.get_secret_value().strip()
        )
        return bool(client_id and client_secret)

    @property
    def rate_limit_trusted_proxy_addresses(
        self,
    ) -> frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        for raw_value in self.trusted_proxy_addresses.split(","):
            value = raw_value.strip()
            if not value:
                continue
            try:
                address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise ValueError(
                    "AC_TRUSTED_PROXY_ADDRESSES must contain comma-separated exact IPs"
                ) from exc
            if not (address.is_private or address.is_loopback):
                raise ValueError(
                    "AC_TRUSTED_PROXY_ADDRESSES must contain only private or loopback IPs"
                )
            addresses.add(address)
        return frozenset(addresses)

    @property
    def allowed_hosts(self) -> list[str]:
        hosts = {
            value.host
            for value in (self.public_app_url, self.admin_app_url, self.api_url)
            if value.host is not None
        }
        hosts.add(self.internal_api_host)
        if self.environment in {"local", "test"}:
            hosts.update({"localhost", "127.0.0.1", "test"})
        return sorted(hosts)

    @property
    def allowed_origins(self) -> list[str]:
        return [str(self.public_app_url).rstrip("/"), str(self.admin_app_url).rstrip("/")]

    @property
    def secure_cookies(self) -> bool:
        return self.environment not in {"local", "test"}


@lru_cache
def get_settings() -> Settings:
    configured = Settings()
    if configured.environment in {"staging", "production"}:
        require_baked_release_id(configured.release_id)
    return configured
