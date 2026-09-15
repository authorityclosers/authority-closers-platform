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
from ac_platform.media.studio_video_limits import STUDIO_VIDEO_MAX_SOURCE_BYTES

_DEPLOYMENT_ORIGINS = {
    "staging": {
        "public_app_url": "https://staging.authorityclosers.com",
        "admin_app_url": "https://admin-staging.authorityclosers.com",
        "coach_app_url": "https://coach-staging.authorityclosers.com",
        "api_url": "https://api-staging.authorityclosers.com",
    },
    "production": {
        "public_app_url": "https://app.authorityclosers.com",
        "admin_app_url": "https://admin.authorityclosers.com",
        "coach_app_url": "https://coach.authorityclosers.com",
        "api_url": "https://api.authorityclosers.com",
    },
}
# Explicit transition aliases, never a wildcard or a cross-environment host.
_DEPLOYMENT_LEARNER_ORIGINS = {
    "staging": "https://learner-staging.authorityclosers.com",
    "production": "https://learner.authorityclosers.com",
}
_SALES_XRAY_ORIGINS = {
    "staging": "https://salesxray-staging.authorityclosers.com",
    "production": "https://salesxray.authorityclosers.com",
}
_DEPLOYMENT_URL_ENV_FIELDS = {
    "public_app_url": "AC_PUBLIC_APP_URL",
    "admin_app_url": "AC_ADMIN_APP_URL",
    "coach_app_url": "AC_COACH_APP_URL",
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
    coach_app_url: AnyHttpUrl = AnyHttpUrl("http://coach.localhost:3102")
    # Optional standalone client. Enabling its host does not enable processing.
    sales_xray_app_url: AnyHttpUrl | None = None
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
    media_max_upload_bytes: int = STUDIO_VIDEO_MAX_SOURCE_BYTES
    media_quota_window_seconds: int = 3600
    media_quota_bytes_per_actor: int = 2 * 1024 * 1024 * 1024
    media_quota_uploads_per_actor: int = 100
    media_max_renditions: int = 6
    media_max_processing_output_bytes: int = 4 * 1024 * 1024 * 1024
    media_max_processing_caption_bytes: int = 25 * 1024 * 1024
    media_allow_range_requests: bool = True
    # Source-owned filesystem media is an explicit deployment profile. It is
    # separate from provider activation and remains inert unless every path
    # and scanner endpoint is configured together.
    media_filesystem_enabled: bool = False
    media_filesystem_root: str | None = None
    media_filesystem_avatar_root: str | None = None
    media_scanner_unix_socket: str | None = None
    media_scanner_host: str | None = None
    media_scanner_port: int = 3310
    media_scanner_total_timeout_seconds: float = 1800.0
    # Explicitly opt-in test fixtures are separate from provider composition.
    # They are accepted only by the staging/test fixture seam and never by
    # production runtime composition.
    media_stress_fixtures_enabled: bool = False
    media_stress_fixtures_cache_root: str | None = None
    # Separate deployment opt-in: loading diagnostic fixtures alone never mounts
    # learner delivery. This flag can serve only the package-owned two-film set.
    media_staging_public_films_delivery_enabled: bool = False
    # Separate disposable-local opt-in; never accepted by deployed settings.
    media_local_public_films_delivery_enabled: bool = False
    # Release-owned, read-only technical films. This is independent of the
    # staging stress fixture and does not activate uploads or a media provider.
    media_public_films_delivery_enabled: bool = False
    media_public_films_root: str | None = None
    media_local_avatar_enabled: bool = False
    media_local_avatar_storage_root: str | None = None
    practice_arcade_preview_enabled: bool = False
    # Separately reviewed deployment opt-in, never inferred from a local flag.
    practice_pilot_enabled: bool = False
    practice_pilot_tenant_id: UUID | None = None

    # Independent opt-in; contains only paths and an approved artifact digest.
    # Provider credentials belong exclusively to the separate inference broker.
    sales_xray_enabled: bool = False
    sales_xray_approval_path: str | None = None
    sales_xray_approval_sha256: str | None = None
    sales_xray_storage_root: str | None = None
    sales_xray_scratch_root: str | None = None
    # Guest admission is a separate release-owned capability. The file contains
    # only the challenge credential; inference credentials remain broker-only.
    sales_xray_acquisition_enabled: bool = False
    sales_xray_acquisition_policy_revision: str | None = None
    sales_xray_challenge_secret_file: str | None = None
    sales_xray_challenge_site_key: str | None = None
    sales_xray_native_socket_path: str | None = None
    sales_xray_native_image_ref: str | None = None

    @field_validator(
        "public_learner_tenant_id",
        "operations_tenant_id",
        "practice_pilot_tenant_id",
        mode="before",
    )
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
        sales_origin = values.get("sales_xray_app_url")
        if sales_origin not in (None, "") and (
            not isinstance(sales_origin, str)
            or sales_origin
            not in {
                _SALES_XRAY_ORIGINS[environment],
                _SALES_XRAY_ORIGINS[environment] + "/",
            }
        ):
            raise ValueError("AC_SALES_XRAY_APP_URL must be the canonical HTTPS origin")
        # Older deployment profiles need not name the not-yet-installed third
        # web service. Its default is still one exact environment-owned origin.
        values.setdefault("coach_app_url", expected_origins["coach_app_url"])
        for field, environment_field in _DEPLOYMENT_URL_ENV_FIELDS.items():
            raw_value = values.get(field)
            if raw_value is None:
                continue
            expected_origin = expected_origins[field]
            allowed = {expected_origin}
            if field == "public_app_url":
                allowed.add(_DEPLOYMENT_LEARNER_ORIGINS[environment])
            if not isinstance(raw_value, str) or raw_value not in {
                candidate for origin in allowed for candidate in (origin, f"{origin}/")
            }:
                raise ValueError(f"{environment_field} must be the canonical HTTPS origin")
        return values

    @field_validator("sales_xray_app_url", mode="before")
    @classmethod
    def require_sales_xray_origin(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        raw = str(value)
        parsed = AnyHttpUrl(raw)
        if (
            raw != raw.strip()
            or parsed.host is None
            or "*" in parsed.host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {None, "/"}
            or "?" in raw
            or "#" in raw
        ):
            raise ValueError("AC_SALES_XRAY_APP_URL must be an exact origin")
        return value

    @field_validator("coach_app_url", mode="before")
    @classmethod
    def require_coach_origin(cls, value: Any) -> Any:
        raw = str(value)
        parsed = AnyHttpUrl(raw)
        if (
            raw != raw.strip()
            or parsed.host is None
            or "*" in parsed.host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {None, "/"}
            or "?" in raw
            or "#" in raw
        ):
            raise ValueError("AC_COACH_APP_URL must be an origin without credentials or path")
        return value

    @model_validator(mode="after")
    def require_deployment_identity_secrets(self) -> Settings:
        if self.sales_xray_app_url is not None and self.sales_xray_app_url.host in {
            self.public_app_url.host,
            self.admin_app_url.host,
            self.coach_app_url.host,
            self.api_url.host,
            self.internal_api_host,
        }:
            raise ValueError("AC_SALES_XRAY_APP_URL must use a distinct application hostname")
        if self.coach_app_url.host in {
            self.public_app_url.host,
            self.admin_app_url.host,
            self.api_url.host,
            self.internal_api_host,
        }:
            raise ValueError("AC_COACH_APP_URL must use a distinct application hostname")
        _ = self.practice_tenant_id  # Reuse the exact runtime admission configuration check.
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
        self._validate_public_films()
        self._validate_media_provider()
        self._validate_filesystem_media()
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
            expected_origin=(
                _DEPLOYMENT_LEARNER_ORIGINS[self.environment]
                if str(self.public_app_url).rstrip("/")
                == _DEPLOYMENT_LEARNER_ORIGINS[self.environment]
                else expected_origins["public_app_url"]
            ),
        )
        self._validate_deployment_url(
            self.admin_app_url,
            field="AC_ADMIN_APP_URL",
            expected_origin=expected_origins["admin_app_url"],
        )
        self._validate_deployment_url(
            self.coach_app_url,
            field="AC_COACH_APP_URL",
            expected_origin=expected_origins["coach_app_url"],
        )
        self._validate_deployment_url(
            self.api_url,
            field="AC_API_URL",
            expected_origin=expected_origins["api_url"],
        )
        if self.sales_xray_app_url is not None:
            self._validate_deployment_url(
                self.sales_xray_app_url,
                field="AC_SALES_XRAY_APP_URL",
                expected_origin=_SALES_XRAY_ORIGINS[self.environment],
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

    @property
    def practice_tenant_id(self) -> UUID | None:
        """Resolve one explicit mode; this is configuration, never actor authority."""

        if self.practice_arcade_preview_enabled and self.practice_pilot_enabled:
            raise ValueError("Practice pilot and local preview cannot both be enabled.")
        if self.practice_arcade_preview_enabled:
            if self.environment not in {"local", "test"}:
                raise ValueError("Editorial Practice Arcade preview is local/test only.")
            return self.public_learner_tenant_id
        if not self.practice_pilot_enabled:
            return None
        if self.environment not in {"test", "staging", "production"}:
            raise ValueError("Practice deployment pilot requires test, staging or production.")
        if (
            self.practice_pilot_tenant_id is None
            or self.practice_pilot_tenant_id != self.public_learner_tenant_id
            or self.operations_tenant_id is None
            or self.practice_pilot_tenant_id == self.operations_tenant_id
        ):
            raise ValueError(
                "Practice pilot requires the exact public learner tenant, distinct from operations."
            )
        return self.practice_pilot_tenant_id

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

    def _validate_filesystem_media(self) -> None:
        """Validate the explicit private filesystem media deployment profile."""

        for field in (
            "media_filesystem_root",
            "media_filesystem_avatar_root",
            "media_scanner_unix_socket",
            "media_scanner_host",
        ):
            value = getattr(self, field)
            if isinstance(value, str) and not value.strip():
                object.__setattr__(self, field, None)
        configured = (
            self.media_filesystem_root,
            self.media_filesystem_avatar_root,
            self.media_scanner_unix_socket,
            self.media_scanner_host,
        )
        if not self.media_filesystem_enabled:
            if any(value is not None and str(value).strip() for value in configured):
                raise ValueError("filesystem media paths require AC_MEDIA_FILESYSTEM_ENABLED=true")
            return
        if self.environment not in {"test", "staging", "production"}:
            raise ValueError("filesystem media requires test, staging, or production")
        if (
            self.media_provider_enabled
            or self.media_stress_fixtures_enabled
            or self.media_public_films_delivery_enabled
            or self.media_staging_public_films_delivery_enabled
            or self.media_local_public_films_delivery_enabled
            or self.media_local_avatar_enabled
        ):
            raise ValueError("filesystem media cannot share provider or fixture activation")
        if self.media_max_upload_bytes != STUDIO_VIDEO_MAX_SOURCE_BYTES:
            raise ValueError("filesystem media requires the exact 2,000,000,000 byte source cap")
        root = self.media_filesystem_root
        avatar_root = self.media_filesystem_avatar_root
        if (
            not root
            or root != root.strip()
            or not Path(root).is_absolute()
            or Path(root).name != "video-objects"
            or ".." in Path(root).parts
            or "://" in root
            or root.startswith(("//", "\\\\"))
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in root)
        ):
            raise ValueError(
                "AC_MEDIA_FILESYSTEM_ROOT must be the absolute video-objects directory"
            )
        if self.environment in {"staging", "production"} and not avatar_root:
            raise ValueError(
                "AC_MEDIA_FILESYSTEM_AVATAR_ROOT must be the absolute avatar-objects directory"
            )
        if avatar_root and (
            avatar_root != avatar_root.strip()
            or not Path(avatar_root).is_absolute()
            or Path(avatar_root).name != "avatar-objects"
            or ".." in Path(avatar_root).parts
            or "://" in avatar_root
            or avatar_root.startswith(("//", "\\\\"))
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in avatar_root)
        ):
            raise ValueError(
                "AC_MEDIA_FILESYSTEM_AVATAR_ROOT must be the absolute avatar-objects directory"
            )
        if avatar_root and Path(avatar_root).parent != Path(root).parent:
            raise ValueError(
                "AC_MEDIA_FILESYSTEM_AVATAR_ROOT must remain beside the video-objects directory"
            )
        if (self.media_scanner_unix_socket is None) == (self.media_scanner_host is None):
            raise ValueError("filesystem media requires exactly one ClamAV endpoint")
        # A deployment uses the scanner's private mounted Unix socket. TCP is
        # retained only for test harnesses and the existing local tunnel.
        if self.environment in {"staging", "production"} and self.media_scanner_unix_socket is None:
            raise ValueError(
                "staging and production filesystem media require the ClamAV Unix socket"
            )
        if not 1 <= self.media_scanner_port <= 65535:
            raise ValueError("AC_MEDIA_SCANNER_PORT must be a valid TCP port")
        if not 0 < self.media_scanner_total_timeout_seconds <= 3600:
            raise ValueError("AC_MEDIA_SCANNER_TOTAL_TIMEOUT_SECONDS must be bounded")

    def _validate_media_stress_fixtures(self) -> None:
        """Keep local fixture opt-in outside production and normal local mode."""

        if self.media_local_avatar_enabled and (
            self.environment != "local"
            or not self.media_local_public_films_delivery_enabled
            or not self.media_local_avatar_storage_root
        ):
            raise ValueError("Local profile uploads require the explicit managed local sandbox.")
        if self.media_local_public_films_delivery_enabled and (
            self.environment != "local"
            or not self.media_stress_fixtures_enabled
            or self.public_learner_tenant_id is None
            or self.media_provider_enabled
            or self.media_staging_public_films_delivery_enabled
        ):
            raise ValueError(
                "local public-film delivery requires the explicit isolated local fixture"
            )

        if self.media_staging_public_films_delivery_enabled and (
            self.environment not in {"staging", "test"}
            or not self.media_stress_fixtures_enabled
            or self.public_learner_tenant_id is None
            or self.media_provider_enabled
        ):
            raise ValueError(
                "staging public-film delivery requires isolated staging/test fixtures, "
                "a configured learner tenant and no general media provider"
            )

        if self.media_stress_fixtures_enabled and self.environment == "production":
            raise ValueError("AC_MEDIA_STRESS_FIXTURES_ENABLED is forbidden in production")
        if (
            self.media_stress_fixtures_enabled
            and not self.media_local_public_films_delivery_enabled
            and self.environment
            not in {
                "test",
                "development",
                "staging",
            }
        ):
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

    def _validate_public_films(self) -> None:
        enabled = self.media_public_films_delivery_enabled
        root = self.media_public_films_root
        if not enabled:
            if root is not None:
                raise ValueError("AC_MEDIA_PUBLIC_FILMS_ROOT requires explicit delivery opt-in")
            return
        if (
            self.environment not in {"test", "staging", "production"}
            or self.public_learner_tenant_id is None
            or self.public_learner_tenant_id.int == 0
            or re.fullmatch(r"[0-9a-f]{40}", self.release_id) is None
            or self.media_provider_enabled
            or self.media_stress_fixtures_enabled
            or self.media_local_public_films_delivery_enabled
            or self.media_staging_public_films_delivery_enabled
            or self.media_local_avatar_enabled
        ):
            raise ValueError(
                "public-film delivery requires its own release, tenant and deployment scope"
            )
        if (
            not root
            or root != root.strip()
            or not Path(root).is_absolute()
            or ".." in Path(root).parts
            or "://" in root
            or root.startswith(("//", "\\\\"))
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in root)
        ):
            raise ValueError("AC_MEDIA_PUBLIC_FILMS_ROOT must be an absolute local directory")
        # Runtime repeats this check before filesystem access. No cross-surface,
        # wildcard, alternate-port or arbitrary public host is admitted.
        origin = str(self.public_app_url).rstrip("/")
        expected = {
            "production": {"https://learner.authorityclosers.com"},
            "staging": {"https://learner-staging.authorityclosers.com"},
            "test": {
                "https://learner.authorityclosers.com",
                "https://learner-staging.authorityclosers.com",
            },
        }
        if origin not in expected[self.environment]:
            raise ValueError("public-film delivery requires the exact learner origin")

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
            for value in (self.public_app_url, self.admin_app_url, self.coach_app_url, self.api_url)
            if value.host is not None
        }
        if self.sales_xray_app_url is not None and self.sales_xray_app_url.host is not None:
            hosts.add(self.sales_xray_app_url.host)
        hosts.add(self.internal_api_host)
        if self.environment in {"local", "test"}:
            hosts.update({"localhost", "127.0.0.1", "test"})
        return sorted(hosts)

    @property
    def allowed_origins(self) -> list[str]:
        origins = [
            str(value).rstrip("/")
            for value in (self.public_app_url, self.admin_app_url, self.coach_app_url)
        ]
        if self.sales_xray_app_url is not None:
            origins.append(str(self.sales_xray_app_url).rstrip("/"))
        return origins

    @property
    def secure_cookies(self) -> bool:
        return self.environment not in {"local", "test"}


@lru_cache
def get_settings() -> Settings:
    configured = Settings()
    if configured.environment in {"staging", "production"}:
        require_baked_release_id(configured.release_id)
    return configured
