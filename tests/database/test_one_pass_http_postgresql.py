"""Admin's analysis pipeline switch and the one-pass comparison over HTTP on PostgreSQL.

Disposable loopback PostgreSQL, fictional rows only (one fictional benchmark call). The
operations-control check has its own tests; here the test's workspace is the operations
workspace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import insert, select, text

from ac_platform.ai_spend import policy
from ac_platform.ai_spend.models import AiSpendSettings
from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.one_pass import admin_http, store
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
OWNER_WORDS = "Owner, 21 Oct 2026: So at least get this on prod now!!!"
ADMIN = "/v1/admin/analysis-pipeline"
MODELS = {"transcription": "gemini-3.1-flash-lite", "analysis": "gemini-3.8-flash"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class _Admitted:
    def __init__(self, application: Any) -> None:
        pass

    async def admit(self, actor: Any) -> None:
        return None


def _bench(connection: Any) -> None:
    """One fictional call read both ways (numbers only; no transcript text needed)."""
    now = datetime.now(UTC)
    classic = store.Outcome(
        state="succeeded",
        reason=None,
        audio_ms=600_000,
        transcription_cost_inr=Decimal("3.6700"),
        analysis_cost_inr=Decimal("8.2000"),
        duration_ms=240_000,
        usage={
            "stages": [
                {"key": "transcription", "label": "Scribe", "inr": 3.67},
                {"key": "coaching", "label": "C5", "inr": 8.2},
            ]
        },
        checks={},
        outputs={"call_objects": [{"type_key": "person.name", "display": "Asha"}]},
    )
    store.insert_classic_bench(
        connection, "fx-01", outcome=classic, models=MODELS, created_by="test", now=now
    )
    subject = store.Subject("bench", bench_call="fx-01")
    started = store.start_run(
        connection,
        subject,
        trigger="bench",
        mode="both",
        settings={"transcription_tier": "standard", "analysis_tier": "standard"},
        models=MODELS,
        created_by="test",
        now=now,
    )
    one = store.Outcome(
        state="succeeded",
        reason=None,
        audio_ms=600_000,
        transcription_cost_inr=Decimal("1.4000"),
        analysis_cost_inr=Decimal("2.6000"),
        transcription_ms=30_000,
        analysis_ms=60_000,
        duration_ms=90_000,
        usage={
            "transcription": {"flex_inr": 0.7, "standard_inr": 1.4},
            "analysis": {"flex_inr": 1.3, "standard_inr": 2.6},
        },
        checks={
            key: "ok"
            for key in ("c2", "c4", "c5", "pointer_review", "call_objects", "prospect_facts")
        },
        outputs={"call_objects": [{"type_key": "person.name", "display": "asha"}]},
    )
    store.finish_run(
        connection,
        subject,
        started,
        one,
        trigger="bench",
        mode="both",
        models=MODELS,
        created_by="test",
        now=now,
    )


def _spend(connection: Any, *, cap: int) -> None:
    config = policy.with_cap(policy.defaults("development"), "one_pass", cap)
    config["background_enabled"] = True
    revision = connection.scalar(text("SELECT coalesce(max(revision), 0) FROM ai_spend_settings"))
    connection.execute(
        insert(AiSpendSettings).values(
            id=uuid4(),
            revision=int(revision) + 1,
            config=policy.validate("development", config),
            reason="test",
            created_by_person_id=None,
            created_at=datetime.now(UTC),
        )
    )


async def _stale(database: Any, session_id: Any, now: Any) -> bool:
    return False


async def _fresh(database: Any, session_id: Any, now: Any) -> bool:
    return True


def test_admin_switches_the_pipeline_and_reads_the_comparison(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(admin_http, "require_admin_surface", lambda request, settings: None)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            staff = RouteContext(
                setup.settings.model_copy(update={"operations_tenant_id": setup.state.tenant_id}),
                setup.require_actor,
                setup.sessions,
            )
            admin_http.install_one_pass_admin_http(setup.app, staff)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                view = (await http.get(ADMIN)).json()
                assert view["environment"] == "development"
                assert view["revision"] is None and view["config"]["mode"] == "classic"
                modes = {m["value"]: m for m in view["modes"]}
                assert modes["classic"]["why_not"] is None and modes["both"]["why_not"] is None
                assert modes["one_pass"]["why_not"] is None and modes["one_pass"]["needs_owner"]
                assert view["confirm"] == "one_pass"
                assert (await http.get(ADMIN, params={"x": "1"})).status_code == 422

                saved = await http.put(
                    f"{ADMIN}/settings",
                    json={
                        "expected_revision": None,
                        "config": {**view["config"], "mode": "both"},
                        "reason": "Owner asked for the side-by-side comparison",
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["revision"] == 1
                assert saved.json()["config"]["mode"] == "both"
                assert saved.json()["history"][0]["reason"].startswith("Owner asked")
                stale = await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": None, "config": {"mode": "classic"}},
                    headers=WRITE,
                )
                assert stale.status_code == 409
                # Showing people one-pass results is the owner's action.
                monkeypatch.setattr(admin_http, "session_is_fresh", _fresh)
                owner = {
                    "expected_revision": 1,
                    "config": {"mode": "one_pass"},
                    "reason": OWNER_WORDS,
                    "confirm": "one_pass",
                }
                for change, status, words in (
                    ({"confirm": None}, 422, "Type one_pass"),
                    ({"confirm": "yes"}, 422, "Type one_pass"),
                    ({"reason": "ok"}, 422, "owner's words"),
                    ({}, 422, "in AI spend first"),
                ):
                    refused = await http.put(
                        f"{ADMIN}/settings", json={**owner, **change}, headers=WRITE
                    )
                    assert refused.status_code == status, refused.text
                    assert words in refused.json()["detail"]
                async with setup.sessions() as db, db.begin():
                    await db.run_sync(lambda sync: _spend(sync.connection(), cap=300))
                monkeypatch.setattr(admin_http, "session_is_fresh", _stale)
                stale = await http.put(f"{ADMIN}/settings", json=owner, headers=WRITE)
                assert stale.status_code == 403 and "Sign in again" in stale.json()["detail"]
                monkeypatch.setattr(admin_http, "session_is_fresh", _fresh)
                switched = await http.put(f"{ADMIN}/settings", json=owner, headers=WRITE)
                assert switched.status_code == 200, switched.text
                assert switched.json()["config"]["mode"] == "one_pass"
                # Back to today's pipeline: one click, no confirm.
                back = await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": 2, "config": {"mode": "classic"}},
                    headers=WRITE,
                )
                assert back.status_code == 200 and back.json()["config"]["mode"] == "classic"
                both = await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": 3, "config": {"mode": "both"}},
                    headers=WRITE,
                )
                assert both.status_code == 200

                empty = (await http.get(f"{ADMIN}/compare")).json()
                assert empty["schema"] == "one-pass-compare/1" and empty["items"] == []
                async with setup.sessions() as db, db.begin():
                    await db.run_sync(lambda sync: _bench(sync.connection()))
                listed = (await http.get(f"{ADMIN}/compare")).json()
                assert [i["subject"] for i in listed["items"]] == [
                    {"kind": "bench", "call": "fx-01"}
                ]
                summary = listed["summary"]["bench"]
                assert summary["calls"] == 1 and summary["audio_minutes"] == 10.0
                assert summary["classic"]["per_minute_inr"] == pytest.approx(1.187)
                assert summary["one_pass"]["per_minute_inr"] == pytest.approx(0.4)
                assert summary["one_pass"]["flex_per_minute_inr"] == pytest.approx(0.2)
                assert listed["summary"]["calls"]["calls"] == 0
                one = (await http.get(f"{ADMIN}/compare/fx-01")).json()
                assert one["differences"]["facts"]["overlap"] == 1.0
                assert one["one_pass"]["checks"]["c5"] == "ok"
                assert (await http.get(f"{ADMIN}/compare/fx-99")).status_code == 404
                assert (await http.get(f"{ADMIN}/compare/{uuid4()}")).status_code == 404
                assert (await http.get(f"{ADMIN}/compare/nonsense")).status_code == 404
                recent = (await http.get(ADMIN)).json()["recent"]  # numbers only
                assert recent[0]["subject"] == "fx-01" and recent[0]["contracts_ok"] == 6
            async with setup.sessions() as db:
                audited = (
                    await db.execute(
                        select(AuditEvent.action, AuditEvent.payload).where(
                            AuditEvent.resource_type == "analysis_pipeline_settings"
                        )
                    )
                ).all()
            assert [action for action, _ in audited] == [
                "analysis_pipeline.settings_saved",
                "analysis_pipeline.one_pass_switched_on",
                "analysis_pipeline.settings_saved",
                "analysis_pipeline.settings_saved",
            ]
            assert audited[0][1]["old"]["mode"] == "classic"
            assert audited[0][1]["new"]["mode"] == "both"
            switched_on = audited[1][1]
            assert switched_on["new"]["mode"] == "one_pass" and switched_on["confirm"] == "one_pass"
            assert switched_on["reason"] == OWNER_WORDS
            assert switched_on["environment"] == "development"
            assert audited[2][1]["new"]["mode"] == "classic"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_admin_prepares_the_gemini_transcription_configuration(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepare saves today's configuration with only C2 on Gemini 3.1 Flash-Lite as a new
    revision; nothing is active or sealed by it (no approval bundle here)."""
    from ac_platform.conversation_intelligence import provider_admin
    from ac_platform.conversation_intelligence.models import (
        ConversationProviderActivation,
        ConversationProviderConfiguration,
    )
    from ac_platform.one_pass import c2_route
    from tests.database.test_conversation_authority_postgresql import _registry_config

    async def admitted(self: Any, actor: Any, **_: Any) -> None:
        return None

    monkeypatch.setattr(admin_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(provider_admin.ConversationProviderAdmin, "admit", admitted)
    monkeypatch.setattr(admin_http, "require_admin_surface", lambda request, settings: None)
    classic = _registry_config(
        "classic-v1", funded=True, text_provider="gemini", text_cost_paise=40
    )

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            state = setup.state
            staff = RouteContext(
                setup.settings.model_copy(update={"operations_tenant_id": state.tenant_id}),
                setup.require_actor,
                setup.sessions,
            )
            admin_http.install_one_pass_admin_http(setup.app, staff)
            path = f"{ADMIN}/transcription"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                empty = (await http.get(path)).json()
                assert empty["active"] is None and empty["gemini"]["saved_revision"] is None
                assert empty["confirm"] == "one_pass"
                nothing = await http.post(f"{path}/prepare", headers=WRITE)
                assert nothing.status_code == 409
                async with setup.sessions() as db, db.begin():
                    row = ConversationProviderConfiguration(
                        id=uuid4(),
                        tenant_id=state.tenant_id,
                        person_id=state.person_id,
                        session_id=state.session_id,
                        revision=1,
                        configuration_sha256=classic.digest,
                        configuration=classic.as_dict(),
                        created_at=datetime.now(UTC),
                    )
                    db.add(row)
                    await db.flush()
                    db.add(
                        ConversationProviderActivation(
                            id=uuid4(),
                            tenant_id=state.tenant_id,
                            person_id=state.person_id,
                            session_id=state.session_id,
                            configuration_id=row.id,
                            configuration_revision=1,
                            configuration_sha256=classic.digest,
                            sequence=1,
                            created_at=datetime.now(UTC),
                        )
                    )
                view = (await http.get(path)).json()
                derived = c2_route.derive_configuration(classic)
                assert view["active"]["transcription"] == {
                    "provider": "elevenlabs",
                    "model": "scribe_v2",
                }
                assert view["gemini"]["configuration_sha256"] == derived.digest
                assert view["gemini"]["saved_revision"] is None
                prepared = await http.post(f"{path}/prepare", headers=WRITE)
                assert prepared.status_code == 200, prepared.text
                body = prepared.json()
                assert body["gemini"]["saved_revision"] == 2
                assert body["gemini"]["approved"] is False  # Root has not sealed it
                assert body["active"]["revision"] == 1  # nothing switched
                again = await http.post(f"{path}/prepare", headers=WRITE)
                assert again.json()["gemini"]["saved_revision"] == 2
            async with setup.sessions() as db:
                saved = await db.scalar(
                    select(ConversationProviderConfiguration.configuration_sha256).where(
                        ConversationProviderConfiguration.revision == 2
                    )
                )
                audited = (
                    await db.execute(
                        select(AuditEvent.action).where(
                            AuditEvent.action == "analysis_pipeline.gemini_transcription_prepared"
                        )
                    )
                ).all()
            assert saved == derived.digest and len(audited) == 1
        finally:
            await setup.engine.dispose()

    run(exercise())
