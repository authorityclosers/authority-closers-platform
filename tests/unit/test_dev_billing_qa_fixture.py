"""The dev fixture guard refuses unsafe targets/authority before any connection."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.settings import Settings
from ac_platform.development import billing_qa_fixture as fixture


def settings() -> Settings:
    return Settings(_env_file=None).model_copy(
        update={
            "environment": "development",
            "database_url": "postgresql+psycopg://ac_runtime@acdev-postgres:5432/ac_platform",
            "public_learner_tenant_id": uuid4(),
            "operations_tenant_id": uuid4(),
            "learner_consent_version": "fictional-dev-consent-v1",
            "billing_fake_provider_signing_key": SecretStr("fictional-fake-key"),
        }
    )


def authority() -> fixture.Authority:
    return fixture.Authority(fixture.OWNER, uuid4(), uuid4(), uuid4(), uuid4())


def environment() -> dict[str, str]:
    return {
        variable: "fictional-fixture-password" for variable in fixture.PASSWORD_VARIABLES.values()
    }


@pytest.mark.parametrize(
    "changes",
    [{"environment": value} for value in ("local", "test", "staging", "production")]
    + [
        {"database_url": value}
        for value in (
            "sqlite://",
            "postgresql+psycopg://ac_runtime@postgres/ac_platform",
            "postgresql+psycopg://ac_runtime@acdev-postgres:5433/ac_platform",
            "postgresql+psycopg://ac_runtime@acdev-postgres/ac_production",
            "postgresql+psycopg://ac_owner@acdev-postgres/ac_platform",
            "postgresql+psycopg://ac_runtime@acdev-postgres/ac_platform?host=production",
            "postgresql+psycopg://ac_runtime@acdev-postgres/ac_platform?options=-csearch_path=elsewhere",
        )
    ]
    + [
        {"billing_allow_live": True},
        {"razorpay_key_id": "fictional-test-key"},
        {"razorpay_key_secret": SecretStr("fictional-key")},
        {"razorpay_webhook_secret": SecretStr("fictional-key")},
    ],
)
def test_unsafe_target_refuses_before_connecting(monkeypatch, changes):
    def connect(*args, **kwargs):
        pytest.fail("Unsafe fixture target reached the database connector")

    monkeypatch.setattr(fixture, "create_async_engine", connect)
    with pytest.raises(ValueError, match="Only the exact development"):
        run_async(fixture.initialize(settings().model_copy(update=changes), environment()))


@pytest.mark.parametrize("variable", ["PGOPTIONS", "PGHOST", "PGSERVICE", "pgHostaddr"])
def test_ambient_postgres_redirects_refuse(variable):
    with pytest.raises(ValueError, match="Only the exact development"):
        fixture.require_target(settings(), {variable: "fictional-redirect"})


@pytest.mark.parametrize("approval", [None, "wrong-owner"])
def test_apply_requires_owner_authority_before_connecting(monkeypatch, approval):
    monkeypatch.setattr(fixture, "create_async_engine", lambda *a, **k: pytest.fail("Connected"))
    recorded = None if approval is None else replace(authority(), approver=approval)
    with pytest.raises(ValueError, match="recorded owner"):
        run_async(fixture.initialize(settings(), environment(), apply=True, authority=recorded))


@pytest.mark.parametrize("variable", fixture.PASSWORD_VARIABLES.values())
def test_missing_secret_names_refuse_before_connecting(monkeypatch, variable):
    monkeypatch.setattr(fixture, "create_async_engine", lambda *a, **k: pytest.fail("Connected"))
    environ = environment()
    del environ[variable]
    with pytest.raises(ValueError, match=f"Missing {variable}"):
        run_async(fixture.initialize(settings(), environ))


def test_missing_fake_signing_key_refuses_before_connecting(monkeypatch):
    monkeypatch.setattr(fixture, "create_async_engine", lambda *a, **k: pytest.fail("Connected"))
    configured = settings().model_copy(update={"billing_fake_provider_signing_key": None})
    with pytest.raises(ValueError, match="AC_BILLING_FAKE_PROVIDER_SIGNING_KEY"):
        run_async(fixture.initialize(configured, environment()))


@pytest.mark.parametrize(
    "missing", ["data_approval", "secrets_approval", "billing_approval", "run_id"]
)
def test_each_recorded_apply_reference_is_required(monkeypatch, capsys, missing):
    monkeypatch.setattr(fixture, "Settings", lambda **kw: settings())
    monkeypatch.setattr(fixture, "create_async_engine", lambda *a, **k: pytest.fail("Connected"))
    args = ["--apply", "--approver", fixture.OWNER]
    for field in ("data_approval", "secrets_approval", "billing_approval", "run_id"):
        if field != missing:
            args += ["--" + field.replace("_", "-"), str(uuid4())]
    assert fixture.main(args) == 2
    assert "refused" in capsys.readouterr().err


def test_cli_does_not_echo_exception_or_argument_values(monkeypatch, capsys):
    sentinel = "fictional-sensitive-value-do-not-print"
    assert fixture.main(["--data-approval", sentinel]) == 2
    assert sentinel not in capsys.readouterr().err

    def invalid_settings(**kwargs):
        raise ValueError(sentinel)

    monkeypatch.setattr(fixture, "Settings", invalid_settings)
    assert fixture.main([]) == 2
    captured = capsys.readouterr()
    assert sentinel not in captured.err + captured.out
