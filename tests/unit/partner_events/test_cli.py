"""Partner events CLI: arguments, dry-run defaults, the Infisical re-exec and the runner's
paging (no process runs, no database: the pipeline is replaced by local fakes)."""

from __future__ import annotations

import asyncio
import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.partner_events import cli, delivery, pipeline
from ac_platform.partner_events.endpoints import EndpointError, validate
from ac_platform.partner_events.payload import Extraction

BASE = ["--service-config", "service.json", "--database-url-file", "database-url"]


def test_every_change_is_a_dry_run_by_default() -> None:
    tenant = str(uuid4())
    for command in (
        ["run"],
        [
            "register-endpoint",
            "--tenant",
            tenant,
            "--url",
            "https://hooks.example.test/sx",
            "--secret-ref",
            "AC_PARTNER_WEBHOOK_SECRET__WISELIFE_DEV",
            "--events",
            "analysis.completed",
            "--facts-profile",
            "wiselife-quote-v1",
            "--reason",
            "fictional",
            "--operator-reference",
            "fictional",
        ],
        ["disable-endpoint", "--endpoint-id", tenant, "--reason", "r", "--operator-reference", "o"],
        ["replay", "--event-id", tenant, "--reason", "r", "--operator-reference", "o"],
        ["test-event", "--endpoint-id", tenant],
    ):
        arguments = cli._arguments([*BASE, *command])
        assert arguments.apply is False
        assert cli._needs_secrets(arguments) is False
    run = cli._arguments([*BASE, "run"])
    assert (run.seconds, run.interval, run.limit, run.daily_cap, run.recent_hours) == (
        55,
        5,
        10,
        300,
        72,
    )
    assert cli._needs_secrets(cli._arguments([*BASE, "run", "--apply"])) is True
    assert cli._needs_secrets(cli._arguments([*BASE, "list"])) is False


@pytest.mark.parametrize(
    "command",
    [
        ["run", "--seconds", "0"],
        ["run", "--daily-cap", "5000"],
        ["register-endpoint", "--tenant", "x"],
        ["register-endpoint", "--tenant", str(uuid4()), "--url", "u", "--secret-ref", "s",
         "--events", "analysis.deleted", "--reason", "r", "--operator-reference", "o"],
    ],
)  # fmt: skip
def test_bad_arguments_are_refused(command: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli._arguments([*BASE, *command])


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"url": "http://hooks.example.test/sx"}, "url_refused"),
        ({"url": "http://127.0.0.1:8787/hook", "environment": "production"}, "url_refused"),
        ({"secret_ref": "GEMINI_API_KEY"}, "secret_ref_invalid"),
        ({"secret_ref_next": "AC_PARTNER_WEBHOOK_SECRET__A"}, "secret_ref_next_invalid"),
        ({"events": []}, "events_invalid"),
        ({"events": ["analysis.completed", "analysis.completed"]}, "events_invalid"),
        ({"facts_profile": "other-v1"}, "facts_profile_unknown"),
    ],
)
def test_endpoint_validation(changes: dict[str, Any], code: str) -> None:
    values: dict[str, Any] = {
        "url": "https://hooks.example.test/sx",
        "secret_ref": "AC_PARTNER_WEBHOOK_SECRET__A",
        "secret_ref_next": None,
        "events": ["analysis.completed"],
        "facts_profile": "wiselife-quote-v1",
        "environment": "development",
    }
    validate(**values)
    validate(**{**values, "url": "http://127.0.0.1:8787/hook"})
    with pytest.raises(EndpointError, match=code):
        validate(**{**values, **changes})


def test_apply_reexecs_inside_infisical_with_the_gemini_secret_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token"
    token.write_text("INFISICAL_TOKEN=fictional-token\n")
    service = tmp_path / "service.json"
    service.write_text(
        json.dumps(
            {
                "environment": "development",
                "providers": [
                    {"provider_id": "elevenlabs", "secret_path_ref": "/other"},
                    {
                        "provider_id": "gemini",
                        "executable": "/usr/local/bin/infisical",
                        "project_ref": "project-fictional",
                        "environment_ref": "dev",
                        "secret_path_ref": "/sales-xray-test/gemini",
                        "token_file_ref": str(token),
                    },
                ],
            }
        )
    )
    captured: dict[str, Any] = {}

    def fake_exec(path: str, command: list[str], environment: dict[str, str]) -> None:
        captured.update(path=path, command=command, environment=environment)

    async def endpoint_active(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr("ac_platform.partner_events.cli.os.execvpe", fake_exec)
    monkeypatch.setattr(cli, "_preflight_async", endpoint_active)
    argv = [
        "--service-config",
        str(service),
        "--database-url-file",
        "database-url",
        "run",
        "--apply",
    ]
    assert cli.main(argv) == 0
    command = captured["command"]
    assert command[0] == "/usr/local/bin/infisical"
    assert command[command.index("--path") + 1] == "/sales-xray-test/gemini"
    assert command[command.index("--env") + 1] == "dev"
    tail = command[command.index("--") + 1 :]
    # The hidden inner flag precedes the subcommand so argparse accepts it.
    assert tail[1:4] == ["-m", "ac_platform.partner_events.cli", "--inner"]
    assert tail[4:] == argv
    assert captured["environment"]["INFISICAL_TOKEN"] == "fictional-token"  # noqa: S105
    assert "GEMINI_API_KEY" not in captured["environment"]


class _Session:
    """Stands in for an AsyncSession: the faked pipeline never touches it."""

    def begin(self) -> _Session:
        return self

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def scalar(self, *args: Any, **kwargs: Any) -> int:
        return 0  # the dry run's count of due events


class _Runner:
    """Fake reports and pipeline steps; records what the runner asked for."""

    def __init__(self, waits: dict[int, str], skips: dict[int, str] | None = None) -> None:
        start = datetime(2026, 10, 18, 4, 0, tzinfo=UTC)
        self.reports = [
            SimpleNamespace(
                endpoint_id=UUID(int=1),
                draft_id=UUID(int=100 + number),
                submission_id=UUID(int=200 + number),
                created_at=start + timedelta(minutes=number),
                facts_profile="wiselife-quote-v1",
                skip=(skips or {}).get(number),
            )
            for number in range(5)
        ]
        self.waits = waits
        self.pages: list[UUID | None] = []
        self.enqueued: list[UUID] = []
        self.final: list[tuple[UUID, str]] = []
        self.extracted: list[UUID] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def active_endpoints(session: Any) -> int:
            return 1

        async def test_sources(session: Any) -> set[str]:
            return set()

        async def candidates(session: Any, **kwargs: Any) -> list[Any]:
            after = kwargs["after"]
            self.pages.append(after[1] if after else None)
            left = [r for r in self.reports if after is None or (r.created_at, r.draft_id) > after]
            return left[: kwargs["limit"]]

        async def extract(sessions: Any, candidate: Any, **kwargs: Any) -> tuple[Any, Any]:
            self.extracted.append(candidate.draft_id)
            number = self.reports.index(candidate)
            if number in self.waits:
                return None, {"facts_wait": self.waits[number]}
            return Extraction("skipped", None), {}

        async def enqueue(sessions: Any, candidate: Any, *args: Any, **kwargs: Any) -> Any:
            self.enqueued.append(candidate.draft_id)
            return {"event": "fictional", "revision": 1, "extraction": "skipped", "facts": 0}

        async def record_final(sessions: Any, candidate: Any, reason: str, **kwargs: Any) -> Any:
            self.final.append((candidate.draft_id, reason))
            return {"final": reason}

        async def aged_out(session: Any, **kwargs: Any) -> list[Any]:
            return []

        async def deliver_one(*args: Any, **kwargs: Any) -> None:
            return None

        async def erasure_sweep(*args: Any, **kwargs: Any) -> dict[str, int]:
            return {"facts_erased": 0, "events_erased": 0}

        for name, value in {
            "active_endpoints": active_endpoints,
            "test_sources": test_sources,
            "candidates": candidates,
            "extract": extract,
            "enqueue": enqueue,
            "record_final": record_final,
            "aged_out": aged_out,
        }.items():
            monkeypatch.setattr(pipeline, name, value)
        monkeypatch.setattr(delivery, "deliver_one", deliver_one)
        monkeypatch.setattr(delivery, "erasure_sweep", erasure_sweep)

    def one_pass(self, *, apply: bool = True, limit: int = 2) -> dict[str, int]:
        totals = dict.fromkeys(
            ("enqueued", "final", "aged_out", "attempts", "delivered", "dropped",
             "dead_letters", "errors", "waiting"),
            0,
        )  # fmt: skip
        arguments = Namespace(apply=apply, limit=limit, recent_hours=72, daily_cap=1)
        active = asyncio.run(
            cli._one_pass(
                _Session,
                arguments,
                environment="test",
                app_url="https://salesxray.example.test",
                client=None,
                call_provider=lambda body: {},
                clock=lambda: datetime(2026, 10, 18, 5, 0, tzinfo=UTC),
                deadline=float("inf"),
                totals=totals,
                cache={},
            )
        )
        assert active is True
        return totals


def test_waiting_reports_never_hold_newer_ones_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # Review 18 Oct, item 5: the three oldest wait on the daily cap; the pass pages past them.
    runner = _Runner({0: "daily_cap", 1: "in_flight", 2: "daily_cap"})
    runner.install(monkeypatch)
    totals = runner.one_pass(limit=2)
    assert runner.enqueued == [runner.reports[3].draft_id, runner.reports[4].draft_id]
    assert totals["waiting"] == 3 and totals["enqueued"] == 2
    assert runner.pages == [None, runner.reports[1].draft_id, runner.reports[3].draft_id]


def test_reports_that_will_never_be_sent_get_a_final_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _Runner(
        {0: "account_inactive", 1: "call_not_ready", 2: "permission_inactive"},
        skips={3: "transcript_revision_missing"},
    )
    runner.install(monkeypatch)
    totals = runner.one_pass(limit=5)
    reports = runner.reports
    assert runner.final == [
        (reports[0].draft_id, "account_inactive"),
        (reports[2].draft_id, "permission_inactive"),
        (reports[3].draft_id, "transcript_revision_missing"),
    ]
    # A call not ready yet waits; a skipped report is never read.
    assert totals["waiting"] == 1 and totals["final"] == 3
    assert reports[3].draft_id not in runner.extracted
    assert runner.enqueued == [reports[4].draft_id]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line.get("final") for line in lines if "final" in line] == [
        "account_inactive",
        "permission_inactive",
        "transcript_revision_missing",
    ]


def test_a_dry_run_records_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _Runner({0: "account_inactive"}, skips={1: "transcript_revision_missing"})
    runner.install(monkeypatch)
    runner.one_pass(apply=False, limit=5)
    assert runner.final == [] and runner.enqueued == []
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["would_record"] for line in lines if "would_record" in line] == [
        "account_inactive",
        "transcript_revision_missing",
    ]


@pytest.mark.parametrize(
    "line,waiting",
    [
        ({"submission": "s", "facts_wait": "daily_cap"}, True),
        ({"submission": "s", "facts": "saved", "enqueue_refused": "call_not_ready"}, True),
        ({"submission": "s", "facts_wait": "account_inactive", "final": "account_inactive"}, False),
        ({"submission": "s", "facts_attempt": 1, "facts_outcome": "refused_stale_source"}, False),
        ({"submission": "s", "error": "ValueError"}, False),
        ({"submission": "s", "event": "e", "revision": 1}, False),
    ],
)
def test_waiting_lines_are_counted_not_logged(line: dict[str, Any], waiting: bool) -> None:
    assert cli._waiting(line) is waiting


@pytest.mark.parametrize(
    "line,reason",
    [
        ({"facts_wait": "account_inactive"}, "account_inactive"),
        ({"facts_wait": "call_erased"}, "call_erased"),
        ({"enqueue_refused": "permission_inactive"}, "permission_inactive"),
        ({"facts_outcome": "refused_call_missing"}, "call_missing"),
        ({"facts_wait": "daily_cap"}, None),
        ({"enqueue_refused": "call_not_ready"}, None),
        ({"enqueue_refused": "stale_source"}, None),
        ({"facts_outcome": "refused_stale_source"}, None),
        ({"facts_outcome": "timeout"}, None),
    ],
)
def test_only_refusals_that_keep_data_in_are_final(
    line: dict[str, Any], reason: str | None
) -> None:
    assert pipeline.final_refusal(line) == reason


@pytest.mark.parametrize(
    "backlog,limit,recorded,alerts",
    [
        # Re-review 18 Oct, m10: a backlog over one page alerts once per run, with the total.
        (5, 2, 5, 1),
        (2, 2, 2, 1),
        (1, 50, 1, 1),
        (0, 2, 0, 0),
        # More than MAX_PAGES pages: the rest wait for the next run (one alert each run).
        (25, 2, 20, 1),
    ],
)
def test_an_aged_out_backlog_alerts_once_per_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    backlog: int,
    limit: int,
    recorded: int,
    alerts: int,
) -> None:
    runner = _Runner({})
    runner.reports = []
    runner.install(monkeypatch)
    old = [
        SimpleNamespace(endpoint_id=UUID(int=number % 2 + 1), draft_id=UUID(int=500 + number))
        for number in range(backlog)
    ]
    done: list[UUID] = []
    sent: list[str] = []

    async def aged_out(session: Any, **kwargs: Any) -> list[Any]:
        return [item for item in old if item.draft_id not in done][: kwargs["limit"]]

    async def record_final(sessions: Any, candidate: Any, reason: str, **kwargs: Any) -> Any:
        assert reason == pipeline.AGED_OUT
        done.append(candidate.draft_id)
        return {"final": reason}

    def notify_owner(text: str) -> str:
        sent.append(text)
        return "absent"

    monkeypatch.setattr(pipeline, "aged_out", aged_out)
    monkeypatch.setattr(pipeline, "record_final", record_final)
    monkeypatch.setattr(delivery, "notify_owner", notify_owner)
    monkeypatch.setattr(cli, "AGE_OUT_LIMIT", limit)
    totals = runner.one_pass()
    assert totals["aged_out"] == recorded and len(done) == recorded
    assert len(sent) == alerts
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    alerted = [line for line in lines if line.get("alert") == "reports_aged_out"]
    assert len(alerted) == alerts
    if alerts:
        assert sent[0].startswith(
            f"Sales X-Ray partner webhooks (test): {recorded} report(s) aged out after 72 h"
        )
        expected = sorted({str(item.endpoint_id)[:8] for item in old[:recorded]})
        assert alerted[0] == {
            "alert": "reports_aged_out",
            "count": recorded,
            "endpoints": expected,
            "notified": "absent",
        }
