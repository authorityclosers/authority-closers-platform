"""Owner/domain boundaries with canonical auth and a mocked DNS resolver."""

from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.organisation_domains import install_organisation_domains_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.tenancy.models import Membership, OrganisationDomainSetting
from tests.unit.http.test_organisation import state as organisation_state  # noqa: F401
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401


@pytest.fixture
def state(organisation_state):  # noqa: F811
    state = organisation_state

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    actor = install_identity_http(state.app, settings=state.settings, sessions=cast(Any, sessions))
    install_organisation_http(state.app, settings=state.settings, require_actor=actor)
    install_organisation_domains_http(state.app, settings=state.settings, require_actor=actor)
    return state


async def call(state, method="GET", path="", *, body=None, token=TOKEN, key=None):
    headers = {"origin": "https://learner.authorityclosers.test"}
    if token is not None:
        headers["cookie"] = f"ac_session={token}"
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url="https://learner.authorityclosers.test",
    ) as client:
        return await client.request(method, "/v1/organisation" + path, headers=headers, json=body)


@pytest.fixture
def resolver(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    result = {
        "Status": 0,
        "Answer": [
            {"name": "_ac-verify.example.test.", "type": 16, "data": '"ac-verify=' + "f" * 43 + '"'}
        ],
    }

    def handle(request):
        calls.append(request)
        assert request.url.host == "cloudflare-dns.com"
        assert dict(request.url.params) == {"name": "_ac-verify.example.test", "type": "TXT"}
        assert request.headers["accept"] == "application/dns-json"
        assert request.extensions["timeout"]["read"] == 5.0
        if isinstance(result.get("failure"), Exception):
            raise result["failure"]
        return httpx.Response(result.get("http_status", 200), json=result)

    def client(**kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(handle)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return calls, result


def body(domains=None, auto_join=True):
    return {
        "verified_domains": ["example.test"] if domains is None else domains,
        "auto_join": auto_join,
    }


async def test_owner_proof_and_append_only_idempotent_settings(state, resolver):
    proof = await call(state, path="/domains/verification?domain=EXAMPLE.test.")
    assert proof.status_code == 200
    assert proof.json() == {
        "record_name": "_ac-verify.example.test",
        "record_value": "ac-verify=" + "f" * 43,
    }
    assert "no-store" in proof.headers["cache-control"]
    key = uuid4()
    response = await call(state, "PUT", "/domains", body=body(), key=key)
    assert response.status_code == 200
    assert response.json() == (await call(state)).json()
    assert response.json()["verified_domains"] == ["example.test"]
    assert (await call(state, "PUT", "/domains", body=body(), key=key)).json() == response.json()
    assert len(resolver[0]) == 1
    changed = await call(state, "PUT", "/domains", body=body(auto_join=False), key=uuid4())
    assert changed.status_code == 200 and changed.json()["auto_join"] is False
    assert len(resolver[0]) == 1  # Existing domains need no repeated external proof.
    assert (
        await call(state, "PUT", "/domains", body=body(auto_join=False), key=key)
    ).status_code == 409
    with Session(state.engine) as db:
        rows = list(
            db.scalars(
                select(OrganisationDomainSetting).order_by(OrganisationDomainSetting.version)
            )
        )
        assert len(rows) == 2 and rows[0].auto_join is True
        assert rows[0].proof["example.test"]["method"] == "dns_txt"
        assert rows[1].proof == {}
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 2
        assert verify_audit_chain_sync(db, state.tenant).valid


@pytest.mark.parametrize(
    "case,expected",
    [
        ("absent", 422),
        ("wrong_token", 422),
        ("wrong_name", 422),
        ("wrong_type", 422),
        ("nxdomain", 422),
        ("unparseable_txt", 422),
        ("timeout", 503),
        ("bad_status", 503),
        ("http_error", 503),
        ("malformed", 503),
    ],
)
async def test_resolver_failures_roll_back_settings_and_audit(state, resolver, case, expected):
    answer = resolver[1]
    if case == "absent":
        answer["Answer"] = []
    elif case in {"wrong_token", "wrong_name", "wrong_type"}:
        key = {"wrong_token": "data", "wrong_name": "name", "wrong_type": "type"}[case]
        answer["Answer"][0][key] = 1 if key == "type" else "incorrect"
    elif case == "nxdomain":
        answer["Status"] = 3
    elif case == "unparseable_txt":
        answer["Answer"][0]["data"] = '"unfinished'
    elif case == "timeout":
        answer["failure"] = httpx.ConnectTimeout("fictional timeout")
    elif case == "bad_status":
        answer["Status"] = 2
    elif case == "http_error":
        answer["http_status"] = 503
    else:
        answer.clear()
    response = await call(state, "PUT", "/domains", body=body(), key=uuid4())
    assert response.status_code == expected
    if expected == 422:
        assert "example.test" in response.json()["detail"]
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(OrganisationDomainSetting)) == 0
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_malformed_txt_does_not_hide_a_valid_record(state, resolver):
    resolver[1]["Answer"].insert(
        0, {"name": "_ac-verify.example.test.", "type": 16, "data": '"unfinished'}
    )
    assert (await call(state, "PUT", "/domains", body=body(), key=uuid4())).status_code == 200


@pytest.mark.parametrize("count,expected", [(20, 200), (21, 422)])
async def test_twenty_domain_limit_is_checked_before_dns(state, resolver, count, expected):
    response = await call(
        state,
        "PUT",
        "/domains",
        body=body(["example.test"] * count),
        key=uuid4(),
    )
    assert response.status_code == expected
    assert len(resolver[0]) == int(expected == 200)


@pytest.mark.parametrize("role", ["admin", "member"])
async def test_non_owner_cannot_read_proof_or_write(state, resolver, role):
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
    assert (await call(state, path="/domains/verification?domain=example.test")).status_code == 403
    assert (await call(state, "PUT", "/domains", body=body(), key=uuid4())).status_code == 403
    assert resolver[0] == []


@pytest.mark.parametrize(
    "domains,expected", [(["gmail.com"], 409), (["staff.gmail.com"], 409), (["invalid"], 422)]
)
async def test_unavailable_and_invalid_domains_do_not_reach_resolver(
    state, resolver, domains, expected
):
    assert (
        await call(state, "PUT", "/domains", body=body(domains), key=uuid4())
    ).status_code == expected
    assert resolver[0] == []


async def test_domain_owned_by_other_organisation_is_refused(state, resolver):
    from ac_platform.tenancy.models import Organisation

    other = state.tenants["Inactive"]
    with Session(state.engine) as db, db.begin():
        db.add(
            Organisation(
                tenant_id=other, creation_command_id=uuid4(), domain_verification_token="x" * 43
            )
        )
        db.flush()
        db.add(
            OrganisationDomainSetting(
                tenant_id=other,
                version=1,
                verified_domains=["example.test"],
                auto_join=False,
                proof={},
                command_id=uuid4(),
            )
        )
    assert (await call(state, "PUT", "/domains", body=body(), key=uuid4())).status_code == 409
    assert resolver[0] == []


async def test_missing_key_and_unsafe_origin_cannot_write(state, resolver):
    assert (await call(state, "PUT", "/domains", body=body())).status_code == 422
    assert (await call(state, "PUT", "/domains", body=body(), key="invalid")).status_code == 422
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url="https://learner.authorityclosers.test",
    ) as client:
        response = await client.put(
            "/v1/organisation/domains",
            json=body(),
            headers={
                "cookie": "ac_session=" + "w" * 43,
                "Idempotency-Key": str(uuid4()),
                "origin": "https://untrusted.example.test",
            },
        )
    assert response.status_code == 403
    assert resolver[0] == []


@pytest.mark.parametrize("selected", [None, "Beta", "Other", "Inactive"])
@pytest.mark.parametrize(
    "method,path", [("GET", "/domains/verification?domain=example.test"), ("PUT", "/domains")]
)
async def test_protected_and_unselected_contexts_are_not_organisations(
    state, resolver, selected, method, path
):
    from ac_platform.identity.models import Session as IdentitySession

    with Session(state.engine) as db, db.begin():
        if selected == "Other":
            db.add(
                Membership(tenant_id=state.tenants[selected], person_id=state.person, role="owner")
            )
            db.flush()
        db.get(IdentitySession, state.session).selected_tenant_id = (
            None if selected is None else state.tenants[selected]
        )
    response = await call(
        state,
        method,
        path,
        body=body() if method == "PUT" else None,
        key=uuid4() if method == "PUT" else None,
    )
    assert response.status_code == 404
    assert resolver[0] == []
