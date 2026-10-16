"""Owner cost step 1 (17 Oct 2026): our own test calls are never scored.

The canary and the QA smoke accounts upload the bundled canary fixture. The
runner drops every report of a test source before admission, so no attempt is
recorded and no provider is called. Disposable-loopback PostgreSQL with the
real imported-report fixture; the provider is a local fake: no network, no key.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence import pointer_review_cli as cli
from ac_platform.conversation_intelligence.canary_cli import FIXTURE_SHA256
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import ReportFixture, _build_fixture
from tests.database.test_pointer_review_admission_postgresql import (
    _provider_answer,
    _report,
    _reviews,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture
def report_fixture(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> ReportFixture:
    fixture: ReportFixture = run(
        _build_fixture(postgres_harness, tmp_path_factory.mktemp("pointer-selection"))
    )
    return fixture


def test_bundled_fixture_is_a_test_source(postgres_harness: Any) -> None:
    async def exercise() -> set[str]:
        engine = create_async_engine(postgres_harness.url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(cli._test_source_shas)
        finally:
            await engine.dispose()

    assert FIXTURE_SHA256 in run(exercise())


def test_runner_never_scores_test_reports(
    postgres_harness: Any,
    report_fixture: ReportFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url_file = tmp_path / "database-url"
    url = postgres_harness.url
    url_file.write_text(url if isinstance(url, str) else url.render_as_string(hide_password=False))
    calls: list[str] = []

    def answer(body: dict[str, Any]) -> dict[str, Any]:
        calls.append("answer")
        return _provider_answer(body)

    async def exercise() -> int:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            real = await _report(sessions, report_fixture)
            test_call = {**real, "submission_id": uuid4(), "source_sha256": FIXTURE_SHA256}
            monkeypatch.setattr(cli, "_latest_reports", lambda *args, **kwargs: [test_call, real])
            arguments = Namespace(
                database_url_file=url_file,
                erase_erased_calls=False,
                recent_hours=None,
                tenant=real["tenant_id"],
                limit=5,
                unscored_only=False,
                apply=True,
                force=False,
                daily_cap=50,
            )
            status = await cli._inner_async(arguments, call_provider=answer)
            assert await _reviews(sessions, real) == 1
            return status
        finally:
            await engine.dispose()

    assert run(exercise()) == 0
    assert calls == ["answer"]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0] == {"reports": 1, "apply": True}
    assert lines[1] == {"test_reports_skipped": 1}
    assert [line.get("outcome") for line in lines[2:]] == ["saved"]
