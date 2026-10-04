"""Receipt CLI: counts and hashes only; fixture text never reaches stdout."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence import sensitive_segments_cli as cli
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.report_export import report_docx_bytes
from ac_platform.conversation_intelligence.sensitive_segments import grams
from ac_platform.http.platform_sensitive_segments import MarkSegmentsRequest
from tests.unit.conversation_intelligence.test_sensitive_segments import S3, envelope
from tests.unit.conversation_intelligence.test_sensitive_segments_loader import (
    TEXTS,
    add_c2,
    insert_mark,
)
from tests.unit.conversation_intelligence.test_sensitive_segments_loader import (
    state as state,
)
from tests.unit.http.test_platform_sensitive_segments import (
    OTHER_REVISION,
    REVISION,
    seed_recording,
)
from tests.unit.http.test_platform_sensitive_segments import marks_state as marks_state
from tests.unit.http.test_workspaces import HttpDatabase
from tests.unit.http.test_workspaces import workspace_state as workspace_state


def test_docx_text_and_overlap_line_count_shared_grams() -> None:
    open_body = json.dumps(envelope(guarded=False)).encode()
    guarded_body = json.dumps(envelope(guarded=True)).encode()
    marked = grams(S3)
    assert cli.overlap_line(open_body, marked)["shared_4grams"] == len(marked)
    assert cli.overlap_line(guarded_body, marked)["shared_4grams"] == 0
    document = report_docx_bytes(envelope(guarded=True))
    assert cli.docx_text(document).count(cli.WITHHELD_MARKER) >= 3
    assert cli.overlap_line(document, marked) == {
        "file_sha256": cli._sha256(document),
        "shared_4grams": 0,
    }
    assert cli.overlap_line(report_docx_bytes(envelope(guarded=False)), marked)["shared_4grams"] > 0


@pytest.mark.asyncio
async def test_receipt_reports_zero_and_the_marker_at_the_path(
    state, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    insert_mark(state, state.recording, "s3")

    async def render_report(self: AcquisitionReports, recording: Any, **_: Any) -> dict[str, Any]:
        return envelope(guarded=True)

    monkeypatch.setattr(AcquisitionReports, "render_report", render_report)
    with Session(state.engine) as db:
        lines = await cli.render_surfaces(
            cast(Any, HttpDatabase(db)), state.recording, ["dimensions[1].evidence[1]"]
        )
    by_surface = {line["surface"]: line for line in lines if "surface" in line}
    assert by_surface["acquisition_report"]["shared_4grams"] == 0
    assert by_surface["acquisition_report"]["markers"] >= 3
    assert by_surface["acquisition_report_docx"]["shared_4grams"] == 0
    assert by_surface["checkpoints"]["shared_4grams"] == 0
    assert by_surface["checkpoints"]["markers"] == 2
    assert lines[-1] == {
        "path": "dimensions[1].evidence[1]",
        "segment_id": "s3",
        "quote_is_marker": True,
    }
    for line in lines:
        print(json.dumps(line, sort_keys=True))
    out = capsys.readouterr().out
    for text in (S3, *TEXTS.values()):
        assert text not in out
    assert "purple" not in out and "lighthouse" not in out


def test_main_refuses_without_a_database_and_prints_no_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AC_DATABASE_URL", raising=False)
    assert cli.main(["receipt", "--recording-id", "11111111-1111-4111-8111-111111111111"]) == 2
    assert cli.main(["overlap", "--recording-id", "x", "--file", "f"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "AC_DATABASE_URL" in captured.err


@pytest.mark.asyncio
async def test_census_scopes_revisions_and_effective_marks_without_text(state):
    add_c2(state, state.recording, OTHER_REVISION, {"s3": "Fictional cash only demo do lakh"})
    mark = insert_mark(state, state.recording, "s3", revision=OTHER_REVISION)
    with Session(state.engine) as db:
        lines = await cli.census_lines(cast(Any, HttpDatabase(db)), [state.recording])
    assert len(lines) == 1 and lines[0]["already_marked"]
    assert lines[0]["run_id"] is None and lines[0]["cited_in_report"] == 0
    assert cli.mark_requests(lines) == []
    insert_mark(state, state.recording, "s3", revision=OTHER_REVISION, release_of=mark)
    with Session(state.engine) as db:
        assert await cli.census_lines(cast(Any, HttpDatabase(db)), [uuid4()]) == []
        lines = await cli.census_lines(cast(Any, HttpDatabase(db)), [state.recording])
    assert not lines[0]["already_marked"]
    assert set(lines[0]) == {
        "recording_id",
        "transcript_revision",
        "run_id",
        "segment_id",
        "category",
        "rule_id",
        "cited_in_report",
        "already_marked",
    }
    request = cli.mark_requests(lines)[0]
    assert MarkSegmentsRequest.model_validate(request["body"]).reason_ref == (
        "AUT-524 census sensitive_terms_v1:cash_only"
    )
    assert "Fictional" not in json.dumps(lines + [request])


@pytest.mark.asyncio
async def test_census_marks_are_specific_to_each_recording(state):
    duplicate = seed_recording(state, revision=REVISION)
    for recording in (state.recording, duplicate):
        add_c2(state, recording, OTHER_REVISION, {"s3": "Fictional cash only demo"})
    insert_mark(state, state.recording, "s3", revision=OTHER_REVISION)
    with Session(state.engine) as db:
        lines = await cli.census_lines(cast(Any, HttpDatabase(db)), [state.recording, duplicate])
    assert len(lines) == 2
    assert {line["recording_id"]: line["already_marked"] for line in lines} == {
        str(state.recording): True,
        str(duplicate): False,
    }
    requests = cli.mark_requests(lines)
    assert len(requests) == 1
    assert requests[0]["path"] == (f"/v1/platform/sensitive-segments/recordings/{duplicate}/marks")


@pytest.mark.asyncio
async def test_census_counts_citations_only_on_the_bound_revision():
    recording, run = uuid4(), uuid4()
    checkpoint = SimpleNamespace(
        recording_id=recording,
        payload={
            "revision": REVISION,
            "segments": [{"id": "s1", "text": "Fictional cash only demo"}],
        },
    )

    def report(revision):
        return SimpleNamespace(
            recording_id=recording,
            run_id=run,
            transcript={"revision": revision},
            payload={"content": {"evidence": [{"segment_id": "s1", "quote": "private"}]}},
        )

    db = SimpleNamespace(
        scalars=AsyncMock(
            side_effect=[
                [checkpoint],
                [report(REVISION), report(REVISION), report(OTHER_REVISION)],
                [],
            ]
        )
    )
    lines = await cli.census_lines(cast(Any, db), [])
    assert db.scalars.await_count == 3
    assert lines[0]["run_id"] == str(run) and lines[0]["cited_in_report"] == 2
    assert "private" not in json.dumps(lines)
    assert len(cli.mark_requests(lines + lines)) == 1


@pytest.mark.asyncio
async def test_receipt_refuses_no_marks(state):
    with Session(state.engine) as db, pytest.raises(cli.CommandError, match="no in-force marks"):
        await cli.render_surfaces(cast(Any, HttpDatabase(db)), state.recording, [])


@pytest.mark.parametrize("is_marker,expected", [(False, 2), (True, 0)])
def test_receipt_path_exit_status(monkeypatch, capsys, is_marker, expected):
    monkeypatch.setattr(
        cli, "receipt", AsyncMock(return_value=[{"path": "missing", "quote_is_marker": is_marker}])
    )
    assert cli.main(["receipt", "--recording-id", str(uuid4()), "--path", "missing"]) == expected
    assert json.loads(capsys.readouterr().out)["quote_is_marker"] == is_marker


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.asyncio
async def test_census_always_rolls_back_and_disposes(monkeypatch, fail):
    transaction, database, engine = AsyncMock(), AsyncMock(), AsyncMock()
    transaction.__aenter__.return_value = transaction
    database.__aenter__.return_value = database
    database.begin = Mock(return_value=transaction)
    monkeypatch.setattr(cli, "_database_url", lambda: "fictional")
    monkeypatch.setattr(cli, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(cli, "async_sessionmaker", Mock(return_value=lambda: database))
    monkeypatch.setattr(
        cli, "census_lines", AsyncMock(side_effect=RuntimeError if fail else None, return_value=[])
    )
    args = SimpleNamespace(recording_id=[], apply=False)
    if fail:
        with pytest.raises(RuntimeError):
            await cli.census(args)
    else:
        assert await cli.census(args) == []
    transaction.rollback.assert_awaited_once()
    database.commit.assert_not_called()
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    "environment,configured,allow",
    [
        (None, "development", False),
        ("staging", "production", True),
        ("production", "production", False),
        ("production", "", True),
    ],
)
@pytest.mark.asyncio
async def test_census_apply_requires_matching_environment_and_production_opt_in(
    monkeypatch,
    environment,
    configured,
    allow,
):
    monkeypatch.setenv("AC_ENVIRONMENT", configured)
    engine = Mock()
    monkeypatch.setattr(cli, "create_async_engine", engine)
    args = cli.parser().parse_args(["census", "--apply"])
    args.environment, args.allow_production = environment, allow
    with pytest.raises(cli.CommandError):
        await cli.census(args)
    engine.assert_not_called()
