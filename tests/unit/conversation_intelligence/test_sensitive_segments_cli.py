"""Receipt CLI: counts and hashes only; fixture text never reaches stdout."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence import sensitive_segments_cli as cli
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.report_export import report_docx_bytes
from ac_platform.conversation_intelligence.sensitive_segments import grams
from tests.unit.conversation_intelligence.test_sensitive_segments import S3, envelope
from tests.unit.conversation_intelligence.test_sensitive_segments_loader import (
    TEXTS,
    insert_mark,
)
from tests.unit.conversation_intelligence.test_sensitive_segments_loader import (
    state as state,
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
