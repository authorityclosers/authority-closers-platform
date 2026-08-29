from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    database_migrator_url: str = (
        "postgresql+psycopg://ac_migrator:local-migrator-only@localhost/ac_platform"
    )
    external_side_effects_hold: bool = True
    email_provider: Literal["fake", "resend"] = "fake"
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None
    public_app_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    admin_app_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3001")
    api_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
