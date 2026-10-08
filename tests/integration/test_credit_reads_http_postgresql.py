"""Fictional authenticated credit GETs in migrated disposable loopback schemas."""

from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, update

from ac_platform.application.settings import Settings
from ac_platform.billing.credit_grants import CreditGrantService
from ac_platform.billing.credit_spend import CreditSpendService
from ac_platform.billing.credits import CreditsLedger
from ac_platform.billing.ledger import BillingLedger
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import install_identity_http
from ac_platform.http.billing import install_billing_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_credits_ledger_postgresql import append
from tests.database.test_credits_ledger_postgresql import lab as ledger_lab
from tests.database.test_credits_ledger_postgresql import postgres_harness as postgres_harness
from tests.unit.http.test_billing_routes import _Commands

ORIGIN = "https://salesxray.example.test"


async def cookie(state, person, selected=None):
    token = uuid4().hex + "f" * 11
    pepper = state.settings.session_token_pepper.get_secret_value().encode()
    async with state.sessions() as database, database.begin():
        await database.execute(
            update(IdentitySession)
            .where(IdentitySession.id == person.session_id)
            .values(token_hash=digest(pepper, token.encode(), sha256), selected_tenant_id=selected)
        )
    return token


@asynccontextmanager
async def lab(postgres_harness):
    async with ledger_lab(postgres_harness) as state:
        state.operations = await seed(state.engine, role="support")
        state.settings = Settings(
            _env_file=None,
            environment="test",
            public_learner_tenant_id=state.owner.tenant_id,
            operations_tenant_id=state.operations.tenant_id,
        )
        async with state.sessions() as database, database.begin():
            database.add(
                Organisation(
                    tenant_id=state.pooled.tenant_id,
                    creation_command_id=uuid4(),
                    domain_verification_token=uuid4().hex * 2,
                )
            )
        state.token = await cookie(state, state.owner)
        state.org_token = await cookie(state, state.organisation, state.pooled.tenant_id)
        state.commands = _Commands()
        state.app = FastAPI()
        register_problem_handlers(state.app)
        actor = install_identity_http(
            state.app, settings=state.settings, sessions=cast(Any, state.sessions)
        )
        install_billing_http(
            state.app, settings=state.settings, require_actor=actor, commands=state.commands
        )
        yield state


async def get(state, path="", *, query=None, token=None):
    headers = {} if token == "" else {"cookie": f"ac_session={token or state.token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app, raise_app_exceptions=False), base_url=ORIGIN
    ) as client:
        return await client.get(f"/v1/billing/credits{path}", params=query, headers=headers)


async def snapshot(state):
    # Counts AND facts include session activity, audit, credit/capacity, usage,
    # order/payment/subscription, settings and entitlement records.
    tables = [
        table
        for name, table in model_metadata().tables.items()
        if name.startswith(("billing_", "audit_", "conversation_", "capability_"))
        or name in {"sessions", "persons", "memberships", "tenants", "organisations", "plans"}
    ]
    async with state.sessions() as database:
        return {
            table.name: list(
                await database.execute(select(table).order_by(*table.primary_key.columns))
            )
            for table in tables
        }


async def minutes(state):
    async with state.sessions() as database:
        ledger = BillingLedger(database)
        personal = await ledger.project_person(
            tenant_id=state.owner.tenant_id,
            person_id=state.owner.person_id,
            now=state.owner.now,
        )
        pooled = await BillingLedger(database, trial_enabled=False).project_organisation(
            tenant_id=state.pooled.tenant_id, now=state.owner.now
        )
        return [
            (
                projection.available_seconds,
                projection.granted_seconds,
                projection.committed_seconds,
                projection.per_call_seconds,
                projection.plan_key,
            )
            for projection in (personal, pooled)
        ]


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_exact_signed_history_traversal_corrections_and_unchanged_facts(
    postgres_harness, monkeypatch
):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                for account, seconds in ((state.personal, 123), (state.pooled, 456)):
                    await BillingLedger(database).write_lot(
                        account=account,
                        kind="grant",
                        seconds=seconds,
                        valid_from=state.owner.now,
                        source_ref=f"fictional:{uuid4()}",
                        actor_type="system",
                        reason="Fictional capacity independent of credits",
                    )
            initial_minutes = await minutes(state)
            async with state.sessions() as database, database.begin():
                quantities = [
                    "123456789012345678901234567890.12345678901234567890123456789",
                    "0.00000000000000000000000000001",
                    "-123456789012345678901234567890",
                    "-0.25",
                    "1.25",
                    "-2",
                ]
                entries = []
                for index, quantity in enumerate(quantities):
                    # Fixed time forces the UUID ordering tie to be meaningful.
                    entries.append(
                        await CreditsLedger(database, clock=lambda: state.owner.now).append(
                            tenant_id=state.personal.tenant_id,
                            account_id=state.personal.id,
                            quantity=Decimal(quantity),
                            source_ref=f"fictional:{uuid4()}",
                            actor_type="system",
                            reason="Fictional read evidence",
                            corrected_entry_id=entries[0].id if index == 3 else None,
                        )
                    )
                await append(database, state.other_personal, Decimal("999.75"))
                await append(database, state.pooled, Decimal("50.125"))
            expected = "-0.87654321098765432109876543210"
            before = await snapshot(state)
            statements = []

            def capture(_conn, _cursor, statement, _params, _context, _many):
                statements.append(statement)

            def fail(*_args, **_kwargs):
                raise AssertionError("GET invoked mutation")

            with monkeypatch.context() as patch:
                for service, method in (
                    (CreditsLedger, "append"),
                    (CreditsLedger, "history"),
                    (BillingLedger, "personal_account"),
                    (BillingLedger, "organisation_account"),
                    (BillingLedger, "mirror_legacy_grants"),
                    (CreditGrantService, "grant"),
                    (CreditSpendService, "spend"),
                ):
                    patch.setattr(service, method, fail)
                event.listen(state.engine.sync_engine, "before_cursor_execute", capture)
                try:
                    with localcontext() as context:
                        context.prec = 2
                        balance = await get(state)
                    assert balance.status_code == 200, balance.text
                    assert balance.json() == {
                        "account": "personal",
                        "account_id": str(state.personal.id),
                        "balance": expected,
                    }
                    private(balance)
                    collected, cursor = [], None
                    for page in range(3):
                        query = {"limit": 2}
                        if cursor:
                            query["before"] = cursor
                        response = await get(state, "/history", query=query)
                        assert response.status_code == 200, response.text
                        private(response)
                        body = response.json()
                        assert set(body) == {"account", "account_id", "entries", "next_before"}
                        collected.extend(body["entries"])
                        cursor = body["next_before"]
                        assert cursor == (body["entries"][-1]["entry_id"] if page < 2 else None)
                    ordered = sorted(
                        entries, key=lambda row: (row.created_at, row.id), reverse=True
                    )
                    assert [row["entry_id"] for row in collected] == [str(e.id) for e in ordered]
                    assert len({row["entry_id"] for row in collected}) == 6
                    for row, entry in zip(collected, ordered, strict=True):
                        assert set(row) == {
                            "entry_id",
                            "quantity",
                            "created_at",
                            "corrected_entry_id",
                        }
                        assert row["quantity"] == format(entry.quantity, "f")
                        assert row["created_at"].endswith("Z")
                        assert row["corrected_entry_id"] == (
                            str(entries[0].id) if entry.id == entries[3].id else None
                        )
                    final = await get(
                        state, "/history", query={"before": collected[-1]["entry_id"]}
                    )
                    assert final.json()["entries"] == [] and final.json()["next_before"] is None
                    default = await get(state, "/history")
                    assert len(default.json()["entries"]) == 6
                    assert state.commands.calls == []
                finally:
                    event.remove(state.engine.sync_engine, "before_cursor_execute", capture)
            assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
            history_sql = [s for s in statements if "LEFT OUTER JOIN billing_credit_entries" in s]
            assert history_sql and all("LIMIT" in s for s in history_sql)
            assert await snapshot(state) == before
            assert await minutes(state) == initial_minutes

    run(exercise())


@pytest.mark.parametrize("kind", ["personal", "organisation"])
def test_eligible_missing_account_and_existing_empty_account_are_read_only(postgres_harness, kind):
    async def exercise():
        async with lab(postgres_harness) as state:
            if kind == "personal":
                new = await seed(state.engine, tenant_id=state.owner.tenant_id)
                token = await cookie(state, new)
            else:
                new = await seed(state.engine, role="owner")
                async with state.sessions() as database, database.begin():
                    database.add(
                        Organisation(
                            tenant_id=new.tenant_id,
                            creation_command_id=uuid4(),
                            domain_verification_token=uuid4().hex * 2,
                        )
                    )
                token = await cookie(state, new, new.tenant_id)
            before = await snapshot(state)
            for path, expected in (
                ("", {"balance": "0"}),
                ("/history", {"entries": [], "next_before": None}),
            ):
                response = await get(state, path, query={"account": kind}, token=token)
                assert response.status_code == 200, response.text
                assert response.json() == {"account": kind, "account_id": None, **expected}
                private(response)
            refused = await get(
                state, "/history", query={"account": kind, "before": str(uuid4())}, token=token
            )
            assert refused.status_code == 404 and refused.json()["code"] == "credit_entry_not_found"
            assert await snapshot(state) == before
            existing_token = state.token if kind == "personal" else state.org_token
            account = state.personal if kind == "personal" else state.pooled
            for path in ("", "/history"):
                response = await get(state, path, query={"account": kind}, token=existing_token)
                assert response.status_code == 200 and response.json()["account_id"] == str(
                    account.id
                )
                assert response.json().get("balance", "0") == "0"
                assert response.json().get("entries", []) == []
            assert await snapshot(state) == before

    run(exercise())


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_org_selection_keeps_personal_public_and_org_current_role(postgres_harness, role):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                database.add(
                    Membership(
                        tenant_id=state.pooled.tenant_id, person_id=state.owner.person_id, role=role
                    )
                )
                await append(database, state.personal, Decimal("1.25"))
                await append(database, state.pooled, Decimal("50.125"))
            token = await cookie(state, state.owner, state.pooled.tenant_id)
            before, minute_values = await snapshot(state), await minutes(state)
            for kind, account, balance in (
                ("personal", state.personal, "1.25"),
                ("organisation", state.pooled, "50.125"),
            ):
                response = await get(state, query={"account": kind}, token=token)
                assert response.status_code == 200, response.text
                assert response.json() == {
                    "account": kind,
                    "account_id": str(account.id),
                    "balance": balance,
                }
                history = await get(state, "/history", query={"account": kind}, token=token)
                assert len(history.json()["entries"]) == 1
                assert history.json()["entries"][0]["quantity"] == balance
                private(response)
            assert await snapshot(state) == before and await minutes(state) == minute_values

    run(exercise())


@pytest.mark.parametrize(
    "failure",
    [
        "member",
        "ended",
        "revoked",
        "stale_owner",
        "unselected",
        "wrong_tenant_query",
        "unregistered",
        "operations",
        "guest",
        "suspended",
        "unverified",
        "ineligible",
        "expired",
        "invalid",
        "revoked_session",
    ],
)
def test_current_authority_refusals_expose_no_credit_and_change_no_facts(postgres_harness, failure):
    async def exercise():
        async with lab(postgres_harness) as state:
            token, kind, status = state.org_token, "organisation", 403
            async with state.sessions() as database, database.begin():
                if failure in {"member", "ended", "revoked", "stale_owner"}:
                    changes = (
                        {"role": "member"}
                        if failure in {"member", "stale_owner"}
                        else {"status": "inactive", "ended_at": state.owner.now}
                    )
                    await database.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == state.pooled.tenant_id,
                            Membership.person_id == state.organisation.person_id,
                        )
                        .values(**changes)
                    )
                elif failure in {"suspended", "unverified"}:
                    token, kind = state.token, "personal"
                    changes = (
                        {"status": "suspended"}
                        if failure == "suspended"
                        else {"email_verified_at": None}
                    )
                    await database.execute(
                        update(Person).where(Person.id == state.owner.person_id).values(**changes)
                    )
                elif failure == "ineligible":
                    token, kind = state.token, "personal"
                    await database.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == state.owner.tenant_id,
                            Membership.person_id == state.owner.person_id,
                        )
                        .values(role="admin")
                    )
                elif failure in {"expired", "revoked_session"}:
                    status = 401
                    changes = (
                        {
                            "expires_at": state.owner.now - timedelta(seconds=1),
                            "created_at": state.owner.now - timedelta(days=2),
                        }
                        if failure == "expired"
                        else {"revoked_at": state.owner.now}
                    )
                    await database.execute(
                        update(IdentitySession)
                        .where(IdentitySession.id == state.organisation.session_id)
                        .values(**changes)
                    )
            if failure == "unselected":
                token = state.token
            elif failure == "wrong_tenant_query":
                token, status = state.token, 422
            elif failure == "unregistered":
                new = await seed(state.engine, role="owner")
                token = await cookie(state, new, new.tenant_id)
            elif failure == "operations":
                kind = "personal"
                token = await cookie(state, state.operations, state.operations.tenant_id)
            elif failure in {"guest", "invalid"}:
                token, status = ("" if failure == "guest" else "x" * 43), 401
            before = await snapshot(state)
            for path in ("", "/history"):
                query = {"account": kind}
                if failure == "wrong_tenant_query":
                    query["tenant_id"] = str(state.pooled.tenant_id)
                response = await get(state, path, query=query, token=token)
                assert response.status_code == status, response.text
                if status == 403:
                    assert response.json()["code"] == "billing_forbidden"
                assert not {"quantity", "balance", "entries", "account_id"} & response.json().keys()
                private(response)
            assert await snapshot(state) == before and state.commands.calls == []

    run(exercise())


def test_two_organisations_read_only_selected_pool_and_scope_cursor(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            other = await seed(state.engine, role="owner")
            async with state.sessions() as database, database.begin():
                database.add(
                    Organisation(
                        tenant_id=other.tenant_id,
                        creation_command_id=uuid4(),
                        domain_verification_token=uuid4().hex * 2,
                    )
                )
                database.add(
                    Membership(
                        tenant_id=other.tenant_id,
                        person_id=state.organisation.person_id,
                        role="admin",
                    )
                )
                foreign_account = await BillingLedger(database).organisation_account(
                    tenant_id=other.tenant_id, create=True
                )
                foreign = await append(database, foreign_account, Decimal("99.75"))
                await append(database, state.pooled, Decimal("50.125"))
            before = await snapshot(state)
            result = await get(state, query={"account": "organisation"}, token=state.org_token)
            assert result.json() == {
                "account": "organisation",
                "account_id": str(state.pooled.id),
                "balance": "50.125",
            }
            history = await get(
                state,
                "/history",
                query={"account": "organisation", "before": str(foreign.id)},
                token=state.org_token,
            )
            assert history.status_code == 404 and history.json()["code"] == "credit_entry_not_found"
            assert await snapshot(state) == before

    run(exercise())


def test_foreign_and_unknown_cursor_have_identical_scoped_refusal(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                own = await append(database, state.personal)
                colleague = await append(database, state.other_personal)
                org = await append(database, state.pooled)
            before = await snapshot(state)
            responses = [
                await get(state, "/history", query={"before": str(entry)})
                for entry in (colleague.id, org.id, uuid4())
            ]
            assert all(r.status_code == 404 for r in responses)
            assert all(r.json() == responses[0].json() for r in responses)
            assert responses[0].json()["code"] == "credit_entry_not_found"
            reverse = await get(
                state,
                "/history",
                query={"account": "organisation", "before": str(own.id)},
                token=state.org_token,
            )
            assert reverse.status_code == 404 and reverse.json() == responses[0].json()
            assert await snapshot(state) == before

    run(exercise())
