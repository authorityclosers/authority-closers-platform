from __future__ import annotations

import os

import pytest

import ac_platform.development.sales_xray_samples as samples

TARGET = {
    "AC_ENVIRONMENT": "development",
    "AC_DATABASE_URL": "postgresql+psycopg://ac_runtime:local-only@127.0.0.1:55432/ac_platform",
    "AC_SALES_XRAY_APP_URL": "https://salesxray-dev.authorityclosers.com",
    "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "true",
}


def test_pinned_dev_target_is_accepted() -> None:
    samples.require_sample_target(TARGET, acknowledged=True)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AC_ENVIRONMENT", "staging"),
        ("AC_ENVIRONMENT", "production"),
        ("AC_ENVIRONMENT", "local"),
        ("AC_DATABASE_URL", "postgresql+psycopg://ac_runtime:p@localhost:55432/ac_platform"),
        ("AC_DATABASE_URL", "postgresql+psycopg://ac_runtime:p@127.0.0.1:5432/ac_platform"),
        ("AC_DATABASE_URL", "postgresql+psycopg://ac_runtime:p@127.0.0.1:55432/other"),
        ("AC_DATABASE_URL", "postgresql+psycopg://other:p@127.0.0.1:55432/ac_platform"),
        (
            "AC_DATABASE_URL",
            "postgresql+psycopg://ac_runtime:p@127.0.0.1:55432/ac_platform?sslmode=require",
        ),
        ("AC_SALES_XRAY_APP_URL", "https://salesxray.authorityclosers.com"),
        ("AC_EXTERNAL_SIDE_EFFECTS_HOLD", "false"),
    ],
)
def test_every_target_guard_refuses(key: str, value: str) -> None:
    environ = dict(TARGET)
    environ[key] = value
    with pytest.raises(samples.SampleRefused):
        samples.require_sample_target(environ, acknowledged=True)


def test_acknowledgement_is_required() -> None:
    with pytest.raises(samples.SampleRefused):
        samples.require_sample_target(TARGET, acknowledged=False)


def test_pg_environment_variables_are_refused() -> None:
    environ = {**TARGET, "PGHOST": "127.0.0.1"}
    with pytest.raises(samples.SampleRefused):
        samples.require_sample_target(environ, acknowledged=True)


@pytest.mark.parametrize(
    ("key", "value", "acknowledged"),
    [
        ("AC_ENVIRONMENT", "production", True),
        ("AC_DATABASE_URL", "postgresql+psycopg://bad@db.invalid/ac_platform", True),
        ("AC_SALES_XRAY_APP_URL", "https://salesxray.authorityclosers.com", True),
        ("AC_EXTERNAL_SIDE_EFFECTS_HOLD", "false", True),
        ("", "", False),
        ("PGHOST", "127.0.0.1", True),
    ],
)
def test_cli_refuses_before_settings_or_database_creation(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str, acknowledged: bool
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("PG"):
            monkeypatch.delenv(name, raising=False)
    for name, target_value in TARGET.items():
        monkeypatch.setenv(name, target_value)
    if key:
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(samples, "Settings", lambda **_: pytest.fail("Settings touched"))
    monkeypatch.setattr(samples, "create_async_engine", lambda *_: pytest.fail("DB touched"))
    args = ["--email", "tester@example.test"]
    if acknowledged:
        args.append("--acknowledge-dev-samples")
    assert samples.main(args) == 2
