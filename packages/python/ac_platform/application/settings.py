from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


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
    database_url: str = "postgresql+psycopg://ac_runtime:local-runtime-only@localhost/ac_platform"
    database_migrator_url: str | None = None
    external_side_effects_hold: bool = True
    email_provider: Literal["fake", "resend"] = "fake"
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None
    public_app_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    admin_app_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3001")
    api_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    session_token_pepper: SecretStr = SecretStr(
        "local-session-token-pepper-change-before-production"
    )
    oauth_transaction_secret: SecretStr = SecretStr(
        "local-oauth-transaction-secret-change-before-production"
    )
    session_cookie_name: str = "ac_session"
    oauth_transaction_cookie_name: str = "ac_oauth_transaction"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None

    @model_validator(mode="after")
    def require_deployment_identity_secrets(self) -> Settings:
        if self.environment not in {"staging", "production"}:
            self._validate_google_oauth_pair()
            return self
        session_pepper = self.session_token_pepper.get_secret_value()
        transaction_secret = self.oauth_transaction_secret.get_secret_value()
        if len(session_pepper.encode("utf-8")) < 32 or session_pepper.startswith("local-"):
            raise ValueError(
                "AC_SESSION_TOKEN_PEPPER must be a non-default value of at least 32 bytes"
            )
        if len(transaction_secret.encode("utf-8")) < 32 or transaction_secret.startswith("local-"):
            raise ValueError(
                "AC_OAUTH_TRANSACTION_SECRET must be a non-default value of at least 32 bytes"
            )
        if session_pepper == transaction_secret:
            raise ValueError("deployment identity secrets must be independent")
        if re.fullmatch(r"[0-9a-f]{40}", self.release_id) is None:
            raise ValueError("AC_RELEASE_ID must be the full lowercase Git commit SHA")
        expected_hosts = (
            {
                "public": "app.authorityclosers.com",
                "admin": "admin.authorityclosers.com",
                "api": "api.authorityclosers.com",
            }
            if self.environment == "production"
            else {
                "public": "staging.authorityclosers.com",
                "admin": "admin-staging.authorityclosers.com",
                "api": "api-staging.authorityclosers.com",
            }
        )
        self._validate_deployment_url(
            self.public_app_url,
            field="AC_PUBLIC_APP_URL",
            expected_host=expected_hosts["public"],
        )
        self._validate_deployment_url(
            self.admin_app_url,
            field="AC_ADMIN_APP_URL",
            expected_host=expected_hosts["admin"],
        )
        self._validate_deployment_url(
            self.api_url,
            field="AC_API_URL",
            expected_host=expected_hosts["api"],
        )
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
        self._validate_google_oauth_pair()
        return self

    @staticmethod
    def _validate_deployment_url(
        value: AnyHttpUrl,
        *,
        field: str,
        expected_host: str,
    ) -> None:
        if value.scheme != "https" or value.host != expected_host or value.path not in {"", "/"}:
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

    def _validate_google_oauth_pair(self) -> None:
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
        if client_id and (
            len(client_id) > 512 or not client_id.endswith(".apps.googleusercontent.com")
        ):
            raise ValueError("AC_GOOGLE_OAUTH_CLIENT_ID is not a Google web client ID")

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_oauth_client_id and self.google_oauth_client_secret)

    @property
    def allowed_hosts(self) -> list[str]:
        hosts = {
            value.host
            for value in (self.public_app_url, self.admin_app_url, self.api_url)
            if value.host is not None
        }
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
    return Settings()
