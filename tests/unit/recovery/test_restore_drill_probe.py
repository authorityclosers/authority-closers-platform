from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ac_platform.recovery import restore_drill_probe

TOKEN = "0123456789ab"  # noqa: S105 - generated identity token, not a credential


def _url(
    *,
    host: str = f"ac-restore-drill-{TOKEN}",
    database: str = f"ac_restore_drill_{TOKEN}",
    role: str = f"ac_restore_owner_{TOKEN}",
    driver: str = "postgresql+psycopg",
    port: int | None = 5432,
    query: str = "",
) -> str:
    endpoint = host if port is None else f"{host}:{port}"
    suffix = f"?{query}" if query else ""
    return f"{driver}://{role}:test-only-password@{endpoint}/{database}{suffix}"


def test_probe_accepts_only_token_matched_disposable_identity() -> None:
    target = restore_drill_probe.validate_probe_target(
        _url(),
        restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
    )

    assert target.token == TOKEN
    assert target.url.host == f"ac-restore-drill-{TOKEN}"
    assert target.url.database == f"ac_restore_drill_{TOKEN}"
    assert target.url.username == f"ac_restore_owner_{TOKEN}"


@pytest.mark.parametrize(
    ("raw_url", "acknowledgement"),
    [
        (_url(), None),
        (
            _url(host="staging-postgres"),
            restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
        ),
        (
            _url(database="ac_restore_drill_aaaaaaaaaaaa"),
            restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
        ),
        (
            _url(role="ac_restore_owner_aaaaaaaaaaaa"),
            restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
        ),
        (
            _url(driver="postgresql"),
            restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
        ),
        (
            _url(port=None),
            restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
        ),
        (
            _url(query="sslmode=require"),
            restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
        ),
    ],
)
def test_probe_rejects_non_drill_or_noncanonical_targets(
    raw_url: str,
    acknowledgement: str | None,
) -> None:
    with pytest.raises(restore_drill_probe.ProbeError):
        restore_drill_probe.validate_probe_target(raw_url, acknowledgement)


def test_probe_failure_does_not_log_database_url_or_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unsafe_url = _url(host="staging-postgres")
    monkeypatch.setenv(restore_drill_probe.DATABASE_URL_ENV, unsafe_url)
    monkeypatch.setenv(
        restore_drill_probe.ACKNOWLEDGEMENT_ENV,
        restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
    )

    result = restore_drill_probe.main(["mark-and-prove", "--reason", "test"])

    captured = capsys.readouterr()
    assert result == 2
    assert unsafe_url not in captured.err
    assert "test-only-password" not in captured.err
    assert captured.out == ""


def test_selected_reconciliation_is_bounded_unique_and_acknowledged() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000001")
    args = SimpleNamespace(
        job_id=[job_id],
        outbox_event_id=[],
        actor_person_id=UUID("00000000-0000-0000-0000-000000000002"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000003"),
        reason="reviewed exact row",
        acknowledge_selected_reconciliation=True,
    )

    selection = restore_drill_probe._selection_from_args(args)

    assert selection.job_ids == (job_id,)
    args.job_id = [job_id, job_id]
    with pytest.raises(restore_drill_probe.ProbeError, match="duplicate"):
        restore_drill_probe._selection_from_args(args)
    args.job_id = [job_id]
    args.acknowledge_selected_reconciliation = False
    with pytest.raises(restore_drill_probe.ProbeError, match="acknowledgement"):
        restore_drill_probe._selection_from_args(args)


@pytest.mark.asyncio
async def test_selected_reconciliation_resolves_persisted_owner_session_and_role_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = UUID("00000000-0000-4000-8000-000000000002")
    tenant_id = UUID("00000000-0000-4000-8000-000000000003")
    session_id = UUID("00000000-0000-4000-8000-000000000004")
    monkeypatch.setenv(restore_drill_probe.OPERATIONS_TENANT_ID_ENV, str(tenant_id))
    database = SimpleNamespace(
        scalar=AsyncMock(return_value=SimpleNamespace(id=session_id, person_id=person_id))
    )
    selection = restore_drill_probe.ReconciliationSelection(
        job_ids=(UUID("00000000-0000-4000-8000-000000000001"),),
        outbox_event_ids=(),
        actor_person_id=person_id,
        tenant_id=tenant_id,
        reason="reviewed exact row",
    )

    actor = await restore_drill_probe._resolve_control_actor(database, selection)

    assert actor.person_id == person_id
    assert actor.session_id == session_id
    assert actor.tenant_id == tenant_id
    assert {"recovery_reconcile", "global_recovery_reconcile"}.issubset(actor.permissions)
    database.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_selected_reconciliation_rejects_mismatched_or_unresolved_control_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_tenant_id = UUID("00000000-0000-4000-8000-000000000003")
    selection = restore_drill_probe.ReconciliationSelection(
        job_ids=(UUID("00000000-0000-4000-8000-000000000001"),),
        outbox_event_ids=(),
        actor_person_id=UUID("00000000-0000-4000-8000-000000000002"),
        tenant_id=UUID("00000000-0000-4000-8000-000000000005"),
        reason="reviewed exact row",
    )
    database = SimpleNamespace(scalar=AsyncMock(return_value=None))
    monkeypatch.setenv(
        restore_drill_probe.OPERATIONS_TENANT_ID_ENV,
        str(configured_tenant_id),
    )

    with pytest.raises(restore_drill_probe.ProbeError, match="configured operations"):
        await restore_drill_probe._resolve_control_actor(database, selection)
    database.scalar.assert_not_awaited()

    matching = restore_drill_probe.ReconciliationSelection(
        job_ids=selection.job_ids,
        outbox_event_ids=(),
        actor_person_id=selection.actor_person_id,
        tenant_id=configured_tenant_id,
        reason=selection.reason,
    )
    with pytest.raises(restore_drill_probe.ProbeError, match="active persisted owner session"):
        await restore_drill_probe._resolve_control_actor(database, matching)


def test_selected_reconciliation_requires_valid_configured_control_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(restore_drill_probe.OPERATIONS_TENANT_ID_ENV, raising=False)
    with pytest.raises(restore_drill_probe.ProbeError, match="not configured"):
        restore_drill_probe._configured_operations_tenant_id()
    monkeypatch.setenv(restore_drill_probe.OPERATIONS_TENANT_ID_ENV, "not-a-uuid")
    with pytest.raises(restore_drill_probe.ProbeError, match="invalid"):
        restore_drill_probe._configured_operations_tenant_id()


@pytest.mark.asyncio
async def test_mark_and_prove_uses_sanctioned_boundary_and_zero_call_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"marker": 0, "disposed": 0, "worker": 0}

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: Any) -> None:
            return None

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        def begin(self) -> FakeTransaction:
            return FakeTransaction()

    class FakeEngine:
        async def dispose(self) -> None:
            calls["disposed"] += 1

    async def fake_marker(_session: Any, *, reason: str) -> tuple[Any, int, int]:
        assert reason == "approved drill"
        calls["marker"] += 1
        return SimpleNamespace(generation=3, status="held"), 2, 4

    class FakeWorker:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            calls["worker"] += 1

        async def prepare(self) -> bool:
            return False

        async def run_once(self) -> None:
            raise restore_drill_probe.WorkerNotReadyError("held")

    monkeypatch.setattr(restore_drill_probe, "create_async_engine", lambda *_a, **_k: FakeEngine())
    monkeypatch.setattr(restore_drill_probe, "async_sessionmaker", lambda *_a, **_k: FakeSession)
    monkeypatch.setattr(restore_drill_probe, "mark_database_restore", fake_marker)
    monkeypatch.setattr(restore_drill_probe, "DurableWorker", FakeWorker)
    target = restore_drill_probe.validate_probe_target(
        _url(),
        restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
    )

    result = await restore_drill_probe.mark_and_prove(target, reason="approved drill")

    assert calls == {"marker": 1, "disposed": 1, "worker": 1}
    assert result["restore_marker"] == {
        "generation": 3,
        "status": "held",
        "held_outbox": 2,
        "held_jobs": 4,
    }
    assert result["worker_hold_proof"] == {
        "worker_ready": False,
        "run_once_rejected": True,
        "provider_calls": 0,
    }


def test_probe_parser_supports_read_only_prove_held_action() -> None:
    args = restore_drill_probe.build_parser().parse_args(["prove-held"])

    assert args.action == "prove-held"


@pytest.mark.asyncio
async def test_prove_held_reads_existing_hold_and_keeps_provider_calls_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"disposed": 0, "worker": 0}

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: Any) -> None:
            return None

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        def begin(self) -> FakeTransaction:
            return FakeTransaction()

    class FakeEngine:
        async def dispose(self) -> None:
            calls["disposed"] += 1

    class FakeRecoveryStateRepository:
        def __init__(self, _session: Any) -> None:
            pass

        async def require_held(self) -> Any:
            return SimpleNamespace(generation=7, status="held")

    class FakeWorker:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            calls["worker"] += 1

        async def prepare(self) -> bool:
            return False

        async def run_once(self) -> None:
            raise restore_drill_probe.WorkerNotReadyError("held")

    monkeypatch.setattr(restore_drill_probe, "create_async_engine", lambda *_a, **_k: FakeEngine())
    monkeypatch.setattr(restore_drill_probe, "async_sessionmaker", lambda *_a, **_k: FakeSession)
    monkeypatch.setattr(
        restore_drill_probe,
        "RecoveryStateRepository",
        FakeRecoveryStateRepository,
    )
    monkeypatch.setattr(restore_drill_probe, "DurableWorker", FakeWorker)
    target = restore_drill_probe.validate_probe_target(
        _url(),
        restore_drill_probe.ACKNOWLEDGEMENT_VALUE,
    )

    result = await restore_drill_probe.prove_held(target)

    assert calls == {"disposed": 1, "worker": 1}
    assert result == {
        "action": "prove-held",
        "recovery_state": {"generation": 7, "status": "held"},
        "worker_hold_proof": {
            "worker_ready": False,
            "run_once_rejected": True,
            "provider_calls": 0,
        },
    }
