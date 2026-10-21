"""The one-pass trial on PostgreSQL: the switch, the spend guard, a run beside today's
pipeline, the ledger, the comparison, erasure and the migration.

Disposable loopback PostgreSQL, fictional rows only. The model is a local fake: no
network, no key, no audio file.
"""

from __future__ import annotations

import importlib.util
from argparse import Namespace
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, insert, inspect, select, text
from sqlalchemy.orm import sessionmaker

from ac_platform.ai_spend import ledger, policy
from ac_platform.ai_spend.models import AiSpendSettings
from ac_platform.db.models import model_metadata
from ac_platform.one_pass import compare, store
from ac_platform.one_pass import settings as choices
from ac_platform.one_pass.gemini import OnePassFailure, Reply
from ac_platform.one_pass.models import OnePassRun
from ac_platform.one_pass.pricing import Usage
from ac_platform.one_pass.runner import run_pass
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import _call
from tests.unit.one_pass.test_one_pass import SEGMENTS, _answer

ROOT = Path(__file__).resolve().parents[2]
TABLES = {"analysis_pipeline_settings", "one_pass_runs"}


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


class FakeGemini:
    """Answers the transcription with the fictional segments and the pass with one answer."""

    name = "fake"

    def __init__(self, fail_analysis: str | None = None) -> None:
        self.fail_analysis = fail_analysis
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, model: str, request: Any, tier: str) -> Reply:
        self.calls.append((model, tier))
        if request.audio is not None:
            usage = Usage(prompt=6_000, audio=5_800, output=900)
            data: dict[str, Any] = {"segments": SEGMENTS}
        else:
            if self.fail_analysis:
                raise OnePassFailure(self.fail_analysis)
            usage = Usage(prompt=14_000, cached=4_000, output=6_000, thoughts=300)
            data = _answer()
        return Reply(data, usage, tier, 1, 1_500, "STOP", "d" * 64)


def _settings(engine: Engine, *, mode: str = "both", cap: int = 200, on: bool = True) -> None:
    now = datetime.now(UTC)
    with engine.begin() as connection:
        if mode != "classic":
            choices.save(
                connection,
                "development",
                {"mode": mode},
                person_id=None,
                reason="test",
                now=now,
            )
        config = policy.with_cap(policy.defaults("development"), "one_pass", cap)
        config["background_enabled"] = on
        revision = connection.scalar(
            text("SELECT coalesce(max(revision), 0) FROM ai_spend_settings")
        )
        connection.execute(
            insert(AiSpendSettings).values(
                id=uuid4(),
                revision=int(revision) + 1,
                config=policy.validate("development", config),
                reason="test",
                created_by_person_id=None,
                created_at=now,
            )
        )


def _pass(engine: Engine, seeded: dict[str, Any], transport: Any) -> list[dict[str, Any]]:
    sessions = sessionmaker(engine, expire_on_commit=False)
    arguments = Namespace(
        recording=seeded["recording_id"],
        recent_hours=48,
        limit=5,
        not_before=datetime.now(UTC) - timedelta(hours=1),
        force=False,
        apply=True,
    )
    return run_pass(
        sessions,
        arguments,
        transport,
        created_by="test:one-pass",
        environment="development",
        audio_reader=lambda _call, _root: (b"ID3fictional", "audio/mpeg"),
    )


def test_both_reads_the_call_beside_todays_pipeline_and_counts_its_spend(
    postgres_harness: Engine,
) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    _settings(postgres_harness)
    model = FakeGemini()
    lines = _pass(postgres_harness, seeded, model)
    assert lines and lines[0]["outcome"] == "succeeded", lines
    assert lines[0]["contracts_ok"] == 6
    # The transcript, then the facts and report requests at once.
    assert [m for m, _ in model.calls] == [
        choices.TRANSCRIPTION_MODEL,
        choices.ANALYSIS_MODEL,
        choices.ANALYSIS_MODEL,
    ]
    with postgres_harness.connect() as connection:
        runs = connection.execute(
            select(OnePassRun.__table__)
            .where(OnePassRun.recording_id == seeded["recording_id"])
            .order_by(OnePassRun.created_at)
        ).all()
        assert [r.state for r in runs] == ["running", "succeeded"]
        done = runs[1]
        assert done.source == "call" and done.mode == "both" and done.trigger == "operator"
        assert done.transcription_cost_inr > 0 and done.analysis_cost_inr > 0
        assert done.cost_inr == done.transcription_cost_inr + done.analysis_cost_inr
        assert done.analysis_cached_tokens == 8_000  # both requests
        assert set(done.usage["analysis"]["requests"]) == {"facts", "report"}
        assert done.transcript["segments"][1]["text"] == SEGMENTS[1]["text"]
        assert set(done.outputs) >= {"c4", "c5", "pointer_review", "call_objects", "prospect_facts"}
        # Spend: one ledger line per stage, under the trial's own feature and cap.
        rows = [
            r
            for r in ledger.read(connection, datetime.now(UTC) - timedelta(hours=1))
            if r.feature == "one_pass"
        ]
        assert sorted(r.model for r in rows) == sorted(
            [choices.TRANSCRIPTION_MODEL, choices.ANALYSIS_MODEL]
        )
        assert sum(r.inr for r in rows) == done.cost_inr
        assert next(r for r in rows if r.model == choices.TRANSCRIPTION_MODEL).audio_ms > 0
        # The comparison reads today's side from today's own tables.
        result = compare.call_compare(connection, recording_id=seeded["recording_id"])
        assert result is not None and result["one_pass"]["available"] is True
        assert result["classic"]["transcript"]["segments"] == 5
        assert result["one_pass"]["checks"]["c5"] == "ok"
        assert result["subject"] == {"kind": "call", "recording_id": str(seeded["recording_id"])}
        listed = compare.overview(connection)
        assert any(
            i["subject"].get("recording_id") == str(seeded["recording_id"]) for i in listed["items"]
        )
    # The same transcript is never read twice.
    assert _pass(postgres_harness, seeded, model) == []


def test_classic_mode_and_the_spend_guard_stop_before_any_provider_call(
    postgres_harness: Engine,
) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    model = FakeGemini()
    assert _pass(postgres_harness, seeded, model) == [{"stopped": "pipeline_classic"}]
    _settings(postgres_harness, cap=0)
    lines = _pass(postgres_harness, seeded, model)
    assert lines[0]["stopped"] == "ai_spend_feature_cap" and lines[0]["feature"] == "one_pass"
    _settings(postgres_harness, cap=200, on=False)
    assert _pass(postgres_harness, seeded, model)[0]["stopped"] == "ai_spend_background_off"
    assert model.calls == []
    with postgres_harness.connect() as connection:
        assert connection.scalar(select(text("count(*)")).select_from(OnePassRun)) == 0


def test_a_failed_pass_keeps_what_it_spent_and_stops_after_two(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    _settings(postgres_harness)
    model = FakeGemini(fail_analysis="provider_http_503")
    first = _pass(postgres_harness, seeded, model)
    assert first[0]["outcome"] == "failed:provider_http_503"
    assert _pass(postgres_harness, seeded, model)[0]["outcome"] == "failed:provider_http_503"
    assert _pass(postgres_harness, seeded, model)[0]["skipped"] == "attempts_exhausted"
    with postgres_harness.connect() as connection:
        failed = connection.execute(
            select(OnePassRun.__table__).where(
                OnePassRun.recording_id == seeded["recording_id"], OnePassRun.state == "failed"
            )
        ).all()
        assert len(failed) == 2
        assert all(r.transcription_cost_inr > 0 and r.analysis_cost_inr is None for r in failed)
        assert all(r.transcript is not None and r.outputs is None for r in failed)


def test_erasure_empties_every_runs_transcript_and_outputs(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    _settings(postgres_harness)
    assert _pass(postgres_harness, seeded, FakeGemini())[0]["outcome"] == "succeeded"
    with postgres_harness.begin() as connection:
        assert store.erase_for_recording(connection, seeded["recording_id"], datetime.now(UTC)) == 2
    with postgres_harness.connect() as connection:
        rows = connection.execute(
            select(
                OnePassRun.transcript, OnePassRun.outputs, OnePassRun.erased_at, OnePassRun.cost_inr
            ).where(OnePassRun.recording_id == seeded["recording_id"])
        ).all()
        assert all(r.transcript is None and r.outputs is None and r.erased_at for r in rows)
        assert any(r.cost_inr for r in rows)  # the numbers stay


def test_settings_keep_revisions_and_staging_stays_classic(postgres_harness: Engine) -> None:
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        assert choices.read(connection, "development") == (choices.defaults(), None)
        choices.save(
            connection, "development", {"mode": "both"}, person_id=None, reason="a", now=now
        )
        choices.save(
            connection,
            "development",
            {"mode": "both", "transcription_tier": "flex"},
            person_id=None,
            reason=None,
            now=now,
        )
        config, revision = choices.read(connection, "development")
        assert revision == 2 and config["transcription_tier"] == "flex"
        # The same saved document reads as classic where a trial may not run.
        assert choices.read(connection, "staging")[0]["mode"] == "classic"
        assert [h["revision"] for h in choices.history(connection)] == [2, 1]
        with pytest.raises(choices.SettingsError):
            choices.save(
                connection, "production", {"mode": "both"}, person_id=None, reason="x", now=now
            )


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261021_0116_one_pass.py"
    spec = importlib.util.spec_from_file_location("one_pass_migration_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_additive_and_passes_the_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261021_0116", "20261020_0115")
    path = Path(module.__file__)
    item = classify_source(path.read_text(), str(path))
    check_operations([item], set())
    assert item.verdict == "additive"


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert set(inspect(connection).get_table_names()) >= TABLES
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert not TABLES & set(inspect(connection).get_table_names())
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_history_requires_forward_recovery(postgres_harness: Engine) -> None:
    with postgres_harness.begin() as connection:
        choices.save(
            connection, "development", {}, person_id=None, reason=None, now=datetime.now(UTC)
        )
    module = migration()
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        module.downgrade()


def test_an_operator_may_read_a_sandbox_call_the_automatic_runner_never_does(
    postgres_harness: Engine,
) -> None:
    from ac_platform.conversation_intelligence.synthetic_import_models import (
        ConversationSandboxOrganisation,
    )
    from ac_platform.tenancy.models import Organisation

    seeded = _call(postgres_harness, lead_name=None)
    _settings(postgres_harness)
    tenant, now = seeded["owner"].tenant_id, datetime.now(UTC)
    with postgres_harness.begin() as connection:
        if (
            connection.scalar(
                select(Organisation.tenant_id).where(Organisation.tenant_id == tenant)
            )
            is None
        ):
            connection.execute(
                insert(Organisation).values(
                    tenant_id=tenant,
                    creation_command_id=uuid4(),
                    domain_verification_token="fictional-" + "x" * 44,
                )
            )
        connection.execute(
            insert(ConversationSandboxOrganisation).values(
                tenant_id=tenant,
                approved_by_person_id=seeded["owner"].person_id,
                approval_reference="fictional-sandbox",
                created_at=now,
            )
        )
    model = FakeGemini()
    sessions = sessionmaker(postgres_harness, expire_on_commit=False)
    automatic = Namespace(
        recording=None,
        recent_hours=48,
        limit=5,
        not_before=now - timedelta(hours=1),
        force=False,
        apply=True,
    )
    lines = run_pass(
        sessions,
        automatic,
        model,
        created_by="test:one-pass",
        environment="development",
        audio_reader=lambda _call, _root: (b"ID3fictional", "audio/mpeg"),
    )
    assert not any("outcome" in line for line in lines) and model.calls == []
    assert _pass(postgres_harness, seeded, model)[0]["outcome"] == "succeeded"
