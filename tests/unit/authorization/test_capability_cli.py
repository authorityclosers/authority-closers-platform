"""Canonical CLI adapter: real relational identity/audit plus isolated terminal boundaries."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.authorization import cli
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.db.models import model_metadata
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant

TOKEN = "synthetic_cli_session_" + "x" * 43  # noqa: S105 - fictional test token
PEPPER = "test-only-cli-pepper-at-least-32-bytes"


class Database:
    def __init__(self, database: Session) -> None:
        self.database = database

    async def __aenter__(self) -> Database:
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.database.close()

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        with self.database.begin():
            yield

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        with self.database.begin_nested():
            yield

    def get_transaction(self) -> Any:
        transaction = self.database.get_transaction()
        return SimpleNamespace(sync_transaction=transaction) if transaction else None

    def get_bind(self) -> Any:
        return self.database.get_bind()

    def add(self, value: Any) -> None:
        self.database.add(value)

    async def scalar(self, statement: Any) -> Any:
        return self.database.scalar(statement)

    async def scalars(self, statement: Any) -> Any:
        return self.database.scalars(statement)

    async def execute(self, statement: Any) -> Any:
        return self.database.execute(statement)

    async def get(self, model: Any, key: Any) -> Any:
        return self.database.get(model, key)

    async def flush(self) -> None:
        self.database.flush()


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: Any, _record: Any) -> None:
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    model_metadata().create_all(engine)
    owner, learner, outsider, operations, academy, session_id = (uuid4() for _ in range(6))
    with Session(engine) as database, database.begin():
        now = datetime.now(UTC)
        database.add_all(
            [
                Tenant(id=operations, slug="test-operations", name="Operations"),
                Tenant(id=academy, slug="test-academy", name="Academy"),
                Person(id=owner, email="owner@example.test", email_verified_at=now),
                Person(id=learner, email="learner@example.test", email_verified_at=now),
                Person(id=outsider, email="outsider@example.test", email_verified_at=now),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=operations, person_id=owner, role="owner"),
                Membership(tenant_id=academy, person_id=owner, role="learner"),
                Membership(tenant_id=academy, person_id=learner, role="learner"),
                IdentitySession(
                    id=session_id,
                    person_id=owner,
                    token_hash=hmac.new(PEPPER.encode(), TOKEN.encode(), hashlib.sha256).digest(),
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )

    class Engine:
        async def dispose(self) -> None:
            pass

    settings = SimpleNamespace(
        database_url="sqlite://unused-adapter",
        operations_tenant_id=operations,
        session_token_pepper=SecretStr(PEPPER),
        release_id="a" * 40,
    )
    monkeypatch.setattr(cli, "create_async_engine", lambda *_args, **_kwargs: Engine())
    monkeypatch.setattr(
        cli, "async_sessionmaker", lambda *_args, **_kwargs: lambda: Database(Session(engine))
    )
    monkeypatch.setattr(cli, "Settings", lambda **_kwargs: settings)
    monkeypatch.setattr(cli, "_read_session_token", lambda: TOKEN)
    monkeypatch.setenv("AC_DATABASE_URL", "sqlite://explicit-test-adapter")
    monkeypatch.delenv("AC_ENVIRONMENT", raising=False)
    yield SimpleNamespace(
        engine=engine,
        owner=owner,
        learner=learner,
        outsider=outsider,
        operations=operations,
        academy=academy,
        session_id=session_id,
        settings=settings,
    )
    engine.dispose()


def arguments(state: SimpleNamespace, action: str = "first-manager", **changes: Any) -> list[str]:
    values: dict[str, Any] = {
        "environment": "local",
        "person-id": state.owner,
    }
    if action != "inspect":
        values.update({"command-id": uuid4(), "reason": "Reviewed test-only capability change"})
    if action == "grant":
        values.update(
            {
                "person-id": state.learner,
                "permission": "catalog_read",
                "scope": "tenant",
                "tenant-id": state.academy,
            }
        )
    values.update(changes)
    result = [action]
    for key, value in values.items():
        if value is not None:
            result.extend((f"--{key}", str(value)))
    return result


def run(
    state: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    action: str = "first-manager",
    **changes: Any,
) -> dict[str, Any]:
    assert cli.main(arguments(state, action, **changes)) == 0
    result = capsys.readouterr()
    assert result.err == ""
    assert TOKEN not in result.out and PEPPER not in result.out
    return json.loads(result.out)


def counts(state: SimpleNamespace) -> dict[str, int]:
    with Session(state.engine) as database:
        return {
            table.name: database.scalar(select(func.count()).select_from(table))
            for table in model_metadata().tables.values()
        }


def test_real_first_manager_replay_creates_only_capability_and_audit(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    before = counts(state)
    command_id = uuid4()
    result = run(
        state, capsys, **{"command-id": command_id, "expected-email": "owner@example.test"}
    )
    assert result == {
        "command_id": str(command_id),
        "grant_id": str(command_id),
        "active": True,
        "replayed": False,
    }
    assert run(state, capsys, **{"command-id": command_id})["replayed"] is True
    after = counts(state)
    assert {
        table: after[table] - before[table] for table in before if after[table] != before[table]
    } == {"capability_grants": 1, "audit_events": 1, "audit_chain_heads": 1}
    with Session(state.engine) as database:
        assert database.get(Membership, (state.academy, state.owner)).role == "learner"
        assert database.get(IdentitySession, state.session_id).revision == 0
        assert verify_audit_chain_sync(database, state.operations).valid


def test_real_grant_inspect_revoke_and_revoked_replay(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    run(state, capsys)
    command_id = uuid4()
    result = run(state, capsys, "grant", **{"command-id": command_id})
    assert result["active"] and not result["replayed"]
    with Session(state.engine) as database:
        before = database.get(IdentitySession, state.session_id).revision
    snapshot = run(state, capsys, "inspect", **{"person-id": state.learner})
    assert snapshot["assignments"][0]["grant_id"] == str(command_id)
    assert snapshot["effective_access_evaluated"] is False
    assert snapshot["assignments"][0]["revoked"] is False
    with Session(state.engine) as database:
        assert database.get(IdentitySession, state.session_id).revision == before
    revoke_id = uuid4()
    assert (
        run(
            state,
            capsys,
            "revoke",
            **{"person-id": state.learner, "grant-id": command_id, "command-id": revoke_id},
        )["active"]
        is False
    )
    assert (
        run(
            state,
            capsys,
            "revoke",
            **{"person-id": state.learner, "grant-id": command_id, "command-id": revoke_id},
        )["replayed"]
        is True
    )
    assert run(state, capsys, "grant", **{"command-id": command_id}) == {
        "command_id": str(command_id),
        "grant_id": str(command_id),
        "active": False,
        "replayed": True,
    }
    with Session(state.engine) as database:
        assert database.get(Membership, (state.academy, state.learner)).role == "learner"
        assert database.scalar(select(func.count()).select_from(CapabilityGrant)) == 2
        assert database.scalar(select(func.count()).select_from(CapabilityRevocation)) == 1
        assert verify_audit_chain_sync(database, state.academy).valid
        audit = database.scalar(select(AuditEvent).where(AuditEvent.tenant_id == state.academy))
        assert audit.actor_person_id == state.owner and audit.session_id == state.session_id


@pytest.mark.parametrize("failure", ["not-owner", "unverified", "email", "missing", "inactive"])
def test_bootstrap_refuses_identity_or_owner_mismatch(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    changes: dict[str, Any] = {}
    if failure == "not-owner":
        changes["person-id"] = state.learner
    elif failure == "email":
        changes["expected-email"] = "different@example.test"
    elif failure == "missing":
        changes["person-id"] = uuid4()
    else:
        with Session(state.engine) as database, database.begin():
            person = database.get(Person, state.owner)
            if failure == "unverified":
                person.email_verified_at = None
            else:
                person.status = "suspended"
    before = counts(state)
    assert cli.main(arguments(state, **changes)) == 2
    assert capsys.readouterr().out == ""
    assert counts(state) == before


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-token",
        "expired",
        "revoked",
        "no-manager",
        "wrong-email",
        "wrong-revoke-subject",
        "no-membership",
    ],
)
def test_normal_commands_require_actual_session_manager_and_exact_subject(
    state: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    if failure != "no-manager":
        run(state, capsys)
    action = "grant"
    changes: dict[str, Any] = {}
    if failure == "wrong-token":
        monkeypatch.setattr(cli, "_read_session_token", lambda: "z" * 64)
    elif failure in {"expired", "revoked"}:
        with Session(state.engine) as database, database.begin():
            session = database.get(IdentitySession, state.session_id)
            if failure == "expired":
                session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                session.created_at = session.expires_at - timedelta(hours=1)
            else:
                session.revoked_at = datetime.now(UTC)
    elif failure == "wrong-email":
        changes["expected-email"] = "different@example.test"
    elif failure == "no-membership":
        changes["person-id"] = state.outsider
    elif failure == "wrong-revoke-subject":
        grant = run(state, capsys, "grant")
        action = "revoke"
        changes.update({"person-id": state.outsider, "grant-id": grant["grant_id"]})
    before = counts(state)
    assert cli.main(arguments(state, action, **changes)) == 2
    assert capsys.readouterr().out == ""
    assert counts(state) == before


def test_governance_fence_precedes_canonical_identity_resolution(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    run(state, capsys)
    order: list[str] = []
    governance, resolve = CapabilityApplication._governance, AsyncIdentityApplication.resolve_actor

    async def fence(self: Any) -> None:
        order.append("governance")
        await governance(self)

    async def identity(self: Any, *args: Any, **kwargs: Any) -> Any:
        order.append("identity")
        return await resolve(self, *args, **kwargs)

    monkeypatch.setattr(CapabilityApplication, "_governance", fence)
    monkeypatch.setattr(AsyncIdentityApplication, "resolve_actor", identity)
    run(state, capsys, "grant")
    assert order[:2] == ["governance", "identity"]


@pytest.mark.parametrize("boundary", ["after-audit", "commit"])
def test_failure_after_real_writes_never_prints_success_or_partial_state(
    state: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    before = counts(state)
    if boundary == "after-audit":
        original = AuditRepository.append

        async def fail(self: Any, **kwargs: Any) -> Any:
            await original(self, **kwargs)
            raise RuntimeError("PRIVATE simulated upstream credential")

        monkeypatch.setattr(AuditRepository, "append", fail)
    else:

        @event.listens_for(Session, "before_commit")
        def fail_commit(_database: Any) -> None:
            raise RuntimeError("PRIVATE native commit failure")

    try:
        assert cli.main(arguments(state)) == 2
        result = capsys.readouterr()
        assert result.out == "" and "PRIVATE" not in result.err
        assert counts(state) == before
    finally:
        if boundary == "commit":
            event.remove(Session, "before_commit", fail_commit)


@pytest.mark.parametrize(
    "change",
    [
        {"command-id": None},
        {"reason": None},
        {"reason": " "},
        {"reason": "x" * 501},
        {"reason": "first\nsecond"},
        {"person-id": "INVALID PRIVATE ID"},
        {"expected-email": "PRIVATE invalid email"},
        {"environment": "production"},
        {"environment": "unknown"},
    ],
)
def test_bad_input_is_sanitized_before_settings_token_or_database(
    state: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
) -> None:
    monkeypatch.setattr(cli, "Settings", lambda **_: pytest.fail("settings must not be reached"))
    monkeypatch.setattr(cli, "_read_session_token", lambda: pytest.fail("stdin must not be read"))
    assert cli.main(arguments(state, **change)) == 2
    result = capsys.readouterr()
    assert result.out == "" and "PRIVATE" not in result.err


@pytest.mark.parametrize(
    "scope",
    [
        {"scope": "platform"},
        {"scope": "program"},
        {"permission": "platform_catalog_write"},
        {"program-id": uuid4()},
    ],
)
def test_scope_shape_and_namespace_rejected_before_connection(
    state: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    scope: dict[str, Any],
) -> None:
    monkeypatch.setattr(cli, "Settings", lambda **_: pytest.fail("no connection expected"))
    assert cli.main(arguments(state, "grant", **scope)) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "case",
    [
        "missing-db",
        "environment-mismatch",
        "missing-operations",
        "settings-failure",
        "baked-release",
    ],
)
def test_configuration_and_baked_release_guard_precede_stdin_and_connection(
    state: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    monkeypatch.setattr(
        cli, "_read_session_token", lambda: pytest.fail("stdin must not be reached")
    )
    monkeypatch.setattr(cli, "create_async_engine", lambda *_a, **_kw: pytest.fail("no connection"))
    changes: dict[str, Any] = {}
    if case == "missing-db":
        monkeypatch.delenv("AC_DATABASE_URL")
    elif case == "environment-mismatch":
        monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    elif case == "missing-operations":
        state.settings.operations_tenant_id = None
    elif case == "settings-failure":

        def invalid(**_kwargs: Any) -> Any:
            raise ValueError("PRIVATE settings credential")

        monkeypatch.setattr(cli, "Settings", invalid)
    else:
        changes["environment"] = "staging"

        def invalid_release(_release: str) -> str:
            raise ValueError("PRIVATE invalid immutable image")

        monkeypatch.setattr(cli, "require_baked_release_id", invalid_release)
    assert cli.main(arguments(state, "grant", **changes)) == 2
    result = capsys.readouterr()
    assert result.out == "" and "PRIVATE" not in result.err


@pytest.mark.parametrize(
    "token", ["", "x" * 42, "x" * 513, " " + "x" * 43, "x" * 43 + " ", "x" * 43 + "é"]
)
def test_hidden_stdin_rejects_unbounded_or_malformed_tokens_without_echo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], token: str
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(token + "\n"))
    with pytest.raises(cli.CliInputError):
        cli._read_session_token()
    result = capsys.readouterr()
    assert result.out == result.err == ""


@pytest.mark.parametrize("length", [43, 512])
def test_stdin_read_has_an_explicit_bound(monkeypatch: pytest.MonkeyPatch, length: int) -> None:
    class Input(io.StringIO):
        def readline(self, size: int = -1) -> str:
            assert size == 514
            return super().readline(size)

    monkeypatch.setattr(cli.sys, "stdin", Input("x" * length + "\r\n"))
    assert cli._read_session_token() == "x" * length


def test_unknown_secret_argument_is_not_repeated(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([*arguments(state), "--session-token", "PRIVATE TOKEN ARGUMENT"]) == 2
    assert "PRIVATE" not in capsys.readouterr().err


def test_terminal_failure_has_no_echo_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Input(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", Input("PRIVATE never read\n"))

    def unavailable() -> str:
        raise OSError("terminal unavailable")

    monkeypatch.setattr(cli, "_read_terminal_token", unavailable)
    with pytest.raises(OSError):
        cli._read_session_token()
    assert "PRIVATE" not in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["x" * 43 + "\r", "x" * 44 + "\b\r"])
def test_windows_terminal_reader_never_echoes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    import sys

    characters = iter(raw)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(getwch=lambda: next(characters)))
    assert cli._read_terminal_token() == "x" * 43
    assert capsys.readouterr().out == capsys.readouterr().err == ""


@pytest.mark.parametrize("failure", [False, True])
def test_posix_terminal_restores_echo_even_if_bounded_read_fails(
    monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    import sys

    previous = [0, 0, 0, 8, 0, 0, []]
    calls: list[Any] = []

    class Input(io.StringIO):
        def fileno(self) -> int:
            return 9

        def readline(self, size: int = -1) -> str:
            assert size == 514
            if failure:
                raise OSError("synthetic read failure")
            return super().readline(size)

    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.sys, "stdin", Input("x" * 43 + "\n"))
    monkeypatch.setitem(
        sys.modules,
        "termios",
        SimpleNamespace(
            ECHO=8,
            TCSAFLUSH=2,
            tcgetattr=lambda _fd: previous,
            tcsetattr=lambda *args: calls.append(args),
        ),
    )
    if failure:
        with pytest.raises(OSError):
            cli._read_terminal_token()
    else:
        assert cli._read_terminal_token() == "x" * 43
    assert calls == [(9, 2, [0, 0, 0, 0, 0, 0, []]), (9, 2, previous)]


def test_first_manager_never_reads_or_issues_a_session(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_session_token", lambda: pytest.fail("no credential required"))
    monkeypatch.setattr(
        AsyncIdentityApplication,
        "issue_authenticated_session",
        lambda *_a, **_kw: pytest.fail("never invent a session"),
    )
    run(state, capsys)


def test_suspended_subject_can_be_inspected_and_revoked_without_reactivation(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    run(state, capsys)
    grant = run(state, capsys, "grant")
    with Session(state.engine) as database, database.begin():
        database.get(Person, state.learner).status = "suspended"
    inspection = run(state, capsys, "inspect", **{"person-id": state.learner})
    assert inspection["effective_access_evaluated"] is False
    assert inspection["assignments"][0]["revoked"] is False
    run(state, capsys, "revoke", **{"person-id": state.learner, "grant-id": grant["grant_id"]})
    with Session(state.engine) as database:
        assert database.get(Person, state.learner).status == "suspended"


def test_success_is_printed_only_after_commit(
    state: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: list[bool] = []

    @event.listens_for(Session, "before_commit")
    def before_commit(_database: Session) -> None:
        assert capsys.readouterr().out == ""
        observed.append(True)

    try:
        run(state, capsys)
        assert observed == [True]
    finally:
        event.remove(Session, "before_commit", before_commit)
