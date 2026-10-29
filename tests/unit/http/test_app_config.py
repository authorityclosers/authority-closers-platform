from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ac_platform.application.settings import Settings
from ac_platform.http.app_config import install_app_config_http, read_app_config


def test_public_defaults_and_cache() -> None:
    app = FastAPI()
    install_app_config_http(app, settings=Settings(_env_file=None, environment="test"))
    with TestClient(app) as client:
        response = client.get("/v1/app/config")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=60"
        assert "set-cookie" not in response.headers
        assert response.json() == {
            "min_app_version": dict.fromkeys(("android", "ios", "desktop"), "0.0.0"),
            "recommended_app_version": dict.fromkeys(("android", "ios", "desktop"), "0.0.0"),
            "features_off": [],
            "message": None,
        }
        assert client.post("/v1/app/config").status_code == 405


def test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AC_APP_MIN_ANDROID_VERSION", "1.2.3")
    monkeypatch.setenv("AC_APP_RECOMMENDED_IOS_VERSION", "2.10.0")
    monkeypatch.setenv("AC_APP_FEATURES_OFF", "press_feedback")
    monkeypatch.setenv("AC_APP_UPDATE_MESSAGE", "A newer app is ready.")
    config = read_app_config(Settings(_env_file=None, environment="test"))
    assert config.min_app_version["android"] == "1.2.3"
    assert config.recommended_app_version["ios"] == "2.10.0"
    assert config.features_off == ["press_feedback"]
    assert config.message == "A newer app is ready."


@pytest.mark.parametrize(
    "version", ["1.2", "01.2.3", "1.2.3-beta", "v1.2.3", "1.2.3\n", "1.2.1000000", "١.2.3", ""]
)
def test_invalid_version_fails_open(version: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        config = read_app_config(Settings(_env_file=None, app_min_android_version=version))
    assert config.min_app_version["android"] == "0.0.0"
    assert "app_min_android_version" in caplog.text
    # Warn about the setting name, never echo untrusted setting contents.
    assert "app_config_invalid_setting" in caplog.text


@pytest.mark.parametrize(
    "features", ["unknown", "press_feedback,unknown", "press_feedback,", " press_feedback"]
)
def test_unknown_features_fail_open(features: str, caplog: pytest.LogCaptureFixture) -> None:
    config = read_app_config(Settings(_env_file=None, app_features_off=features))
    assert config.features_off == []
    assert "app_features_off" in caplog.text


@pytest.mark.parametrize("message", ["x" * 281, "<b>Update</b>", "update\nnow"])
def test_invalid_message_is_omitted(message: str) -> None:
    config = read_app_config(Settings(_env_file=None, app_update_message=message))
    assert config.message is None
