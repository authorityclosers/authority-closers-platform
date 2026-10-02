"""Canary refusal and disabled paths must not expose secrets or open a database."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import canary_cli as cli
from tests.conversation_overview_fixtures import overview_for


def test_http_cannot_mark_canary() -> None:
    root = Path(cli.__file__).parents[1] / "http"
    assert not [p for p in root.rglob("*.py") if "mark_canary_submission" in p.read_text()]


def test_disabled_never_opens_database(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "development")
    monkeypatch.setenv("AC_DATABASE_URL", "unused-sensitive-connection")
    monkeypatch.setattr(cli, "Settings", lambda **_: SimpleNamespace())
    monkeypatch.setattr(cli, "load_pinned_approval", lambda _: None)
    monkeypatch.setattr(cli, "create_async_engine", lambda *a, **k: pytest.fail("database opened"))
    assert cli.main(["--environment", "development", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["stage_reached"] == "disabled"
    assert result["retention_ref"] is None


@pytest.mark.parametrize(
    "args",
    [
        ["--environment", "production"],
        ["--environment", "staging"],
        ["--environment", "development", "--timeout-seconds", "1801"],
        ["--environment", "accidental-sensitive-value"],
    ],
)
def test_refusal_is_generic(monkeypatch, capsys, args) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "development")
    monkeypatch.setenv("AC_DATABASE_URL", "unused-sensitive-connection")
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert not output.out and "sensitive" not in output.err


@pytest.mark.parametrize(
    ("scenario", "exit_code", "stage", "failure"),
    [
        ("success", 0, "C6", None),
        ("C4_failure", 1, "C4", "stage_failed"),
        ("over_cap", 1, "C1", "canary_quote_over_cap"),
        ("timeout", 1, "C4", "timeout"),
        ("unexpected", 1, "C4", "canary_failed"),
        ("invalid_report", 1, "C5", "report_contract_invalid"),
        ("no_authority", 2, None, None),
        ("bad_config", 2, None, None),
        ("cleanup", 1, "C6", "canary_failed"),
    ],
)
def test_scripted_pipeline(monkeypatch, capsys, tmp_path, scenario, exit_code, stage, failure):
    """Script worker progress; keep the CLI, cap, consent and overview checks real."""
    identifier, clock_tick = uuid4(), 0
    real_sleep = asyncio.sleep
    checkpoints = SimpleNamespace(all=lambda: [SimpleNamespace(stage="C1")])
    db = SimpleNamespace(scalars=AsyncMock(return_value=checkpoints))

    @asynccontextmanager
    async def session(*args, **kwargs):
        yield db

    db.begin = session
    owner = SimpleNamespace(
        sessions=SimpleNamespace(tenant_id=identifier),
        resolve_processing_actor=AsyncMock(return_value=object()),
    )
    runtime = SimpleNamespace(
        policy=SimpleNamespace(retention_days=7, retention_ref="ref:retention:standard"),
        authority=None if scenario == "no_authority" else object(),
        storage=SimpleNamespace(root=tmp_path),
        scratch=SimpleNamespace(root=tmp_path),
    )
    cleanup_error = RuntimeError("accidental-sensitive-value") if scenario == "cleanup" else None
    engine = SimpleNamespace(dispose=AsyncMock(side_effect=cleanup_error))
    settings = SimpleNamespace(
        public_learner_tenant_id=uuid4(),
        sales_xray_enabled=True,
        sales_xray_acquisition_enabled=True,
        database_url="unused",
        sales_xray_native_socket_path="unused",
        sales_xray_native_image_ref="unused",
    )
    quote = {
        "id": str(identifier),
        "plan_fingerprint": "a" * 64,
        "privacy_revision": "sales-xray-processing-plan-v1",
        "max_cost_paise": 45_001 if scenario == "over_cap" else 45_000,
    }
    plans = SimpleNamespace(quote=AsyncMock(return_value=quote), accept=AsyncMock())

    async def progress(*args, **kwargs):
        nonlocal clock_tick
        tick, clock_tick = clock_tick, clock_tick + 1
        if tick == 2 and scenario == "timeout":
            await real_sleep(2)
        if tick == 2 and scenario in {"unexpected", "bad_config"}:
            error = RuntimeError if scenario == "unexpected" else ValueError
            raise error("accidental-sensitive-value")
        return {
            "recording_id": str(identifier),
            "local_state": "completed",
            "state": "active",
            "execution_hold": None,
            "failure_code": None,
            "has_report": tick >= 2,
            "stages": []
            if tick == 0
            else [
                {
                    "stage": "C4" if tick == 1 else "C5",
                    "state": "failed" if scenario == "C4_failure" else "completed",
                }
            ],
        }

    overview = overview_for({"strengths": [], "improvements": []})
    content = {"overview": None if scenario == "invalid_report" else overview}
    reports = SimpleNamespace(
        application=object(),
        progress=progress,
        report=AsyncMock(return_value={"report": {"content": content}}),
    )
    db.run = AsyncMock(return_value=object())  # native preflight executes no external process
    monkeypatch.setenv("AC_ENVIRONMENT", "development")
    monkeypatch.setenv("AC_DATABASE_URL", "unused-sensitive-connection")
    for name, replacement in {
        "Settings": lambda **kw: settings,
        "load_pinned_approval": lambda s: SimpleNamespace(
            acquisition_policy_for=lambda tenant_id: object()
        ),
        "compose_hosted_intake": lambda s: runtime,
        "SocketNativeRuntime": lambda *a, **kw: object(),
        "create_async_engine": lambda *a, **kw: engine,
        "async_sessionmaker": lambda *a, **kw: session,
        "_FencedExecutor": session,
        "ownership": lambda *a: owner,
        "submit": AsyncMock(return_value="in-memory-only-visitor-token"),
        "AcquisitionReports": lambda *a: reports,
        "ConversationProcessingPlans": lambda *a: plans,
    }.items():
        monkeypatch.setattr(cli, name, replacement)
    monkeypatch.setattr(cli.asyncio, "sleep", AsyncMock())
    assert (
        cli.main(["--environment", "development", "--timeout-seconds", "1", "--json"]) == exit_code
    )
    output = capsys.readouterr()
    assert "sensitive" not in output.out + output.err
    assert "visitor-token" not in output.out + output.err
    engine.dispose.assert_awaited_once()
    if exit_code == 2:
        assert not output.out and "refused" in output.err
        return
    result = json.loads(output.out)
    assert set(result) == {
        "ok",
        "environment",
        "stage_reached",
        "failure_code",
        "seconds_per_stage",
        "total_seconds",
        "cost_paise",
        "report_present",
        "retention_ref",
    }
    assert result["retention_ref"] == "ref:retention:standard"
    assert result["ok"] == (scenario == "success")
    assert (result["stage_reached"], result["failure_code"]) == (stage, failure)
    assert result["report_present"] == (scenario in {"success", "invalid_report", "cleanup"})
    assert result["cost_paise"] == quote["max_cost_paise"]
    assert result["total_seconds"] >= 0
    assert all(seconds >= 0 for seconds in result["seconds_per_stage"].values())
    assert plans.accept.await_count == (0 if scenario == "over_cap" else 1)
    if scenario != "over_cap":
        assert plans.accept.await_args.args[2].plan_fingerprint == quote["plan_fingerprint"]


KEEP = "ref:retention/sales-xray-keep-for-training/v1"


@pytest.mark.parametrize(
    ("environment", "days", "ref", "allowed"),
    [
        ("development", 3650, KEEP, True),
        ("staging", 3650, KEEP, True),
        ("production", 3650, KEEP, False),
        ("production", 7, KEEP, False),
        ("production", 7, "ref:retention:standard", True),
        ("development", 7, "ref:retention:standard", True),
        ("staging", 7, "ref:retention:standard", True),
        ("development", 30, "ref:retention:standard", False),
        ("staging", 30, "ref:retention:standard", False),
        ("production", 30, "ref:retention:standard", False),
    ],
)
def test_retention_by_environment(monkeypatch, capsys, environment, days, ref, allowed) -> None:
    """Keep-for-training runs only off production; refusals print JSON and exit non-zero."""
    monkeypatch.setenv("AC_ENVIRONMENT", environment)
    monkeypatch.setenv("AC_DATABASE_URL", "unused-sensitive-connection")
    settings = SimpleNamespace(
        public_learner_tenant_id=uuid4(),
        sales_xray_enabled=True,
        sales_xray_acquisition_enabled=True,
        database_url="unused",
        sales_xray_native_socket_path="unused",
        sales_xray_native_image_ref="unused",
        release_id="unused",
    )
    runtime = SimpleNamespace(
        policy=SimpleNamespace(retention_days=days, retention_ref=ref),
        scratch=SimpleNamespace(root=Path("unused")),
    )

    engine = Mock(side_effect=ValueError("pipeline reached"))
    for name, replacement in {
        "Settings": lambda **kw: settings,
        "require_baked_release_id": lambda _: None,
        "load_pinned_approval": lambda s: SimpleNamespace(
            acquisition_policy_for=lambda tenant_id: object()
        ),
        "compose_hosted_intake": lambda s: runtime,
        "SocketNativeRuntime": lambda *a, **kw: object(),
        "create_async_engine": engine,
    }.items():
        monkeypatch.setattr(cli, name, replacement)
    argv = ["--environment", environment, "--json"]
    if environment == "production":
        argv.append("--allow-production")
    code = cli.main(argv)
    output = capsys.readouterr()
    if allowed:
        engine.assert_called_once_with(settings.database_url, pool_pre_ping=True)
        assert code == 2 and not output.out
        return
    engine.assert_not_called()
    assert code == 1
    result = json.loads(output.out)
    assert result["ok"] is False
    assert (result["stage_reached"], result["failure_code"]) == (
        "refused",
        "canary_refused_retention",
    )
    assert result["retention_ref"] == ref
