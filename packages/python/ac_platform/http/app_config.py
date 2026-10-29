"""Public, non-personal compatibility settings. Invalid switches fail open."""

from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Response
from pydantic import BaseModel

from ac_platform.application.settings import Settings

logger = logging.getLogger(__name__)
PLATFORMS = ("android", "ios", "desktop")
KNOWN_FEATURES = frozenset({"press_feedback"})
VERSION = re.compile(
    r"(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})", re.ASCII
)


class AppConfig(BaseModel):
    min_app_version: dict[str, str]
    recommended_app_version: dict[str, str]
    features_off: list[str]
    message: str | None = None


def read_app_config(settings: Settings) -> AppConfig:
    versions: dict[str, dict[str, str]] = {"min": {}, "recommended": {}}
    for kind, values in versions.items():
        for platform in PLATFORMS:
            key = f"app_{kind}_{platform}_version"
            value = getattr(settings, key)
            if VERSION.fullmatch(value) is None:
                logger.warning("app_config_invalid_setting: %s", key)
                value = "0.0.0"
            values[platform] = value
    raw = settings.app_features_off
    features = raw.split(",") if raw else []
    if any(key not in KNOWN_FEATURES for key in features):
        logger.warning("app_config_invalid_setting: app_features_off")
        features = []
    message = settings.app_update_message
    if len(message) > 280 or any(ord(char) < 32 or char in "<>" for char in message):
        logger.warning("app_config_invalid_setting: app_update_message")
        message = ""
    return AppConfig(
        min_app_version=versions["min"],
        recommended_app_version=versions["recommended"],
        features_off=sorted(set(features)),
        message=message or None,
    )


def install_app_config_http(application: FastAPI, *, settings: Settings) -> None:
    config = read_app_config(settings)

    @application.get("/v1/app/config", response_model=AppConfig, tags=["app-config"])
    async def app_config(response: Response) -> AppConfig:
        response.headers["Cache-Control"] = "public, max-age=60"
        return config
