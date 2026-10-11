"""Candidate username acceptance over TCP using the complete API composition.

Only disposable loopback PostgreSQL and fictional identities are used. The
receipt contains statuses and assertions, never credentials or response bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import select as fd_select
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.integration.test_password_identity_http_postgresql import _Harness
from tests.integration.test_username_accounts_postgresql import account

ROOT = Path(__file__).parents[2]
SERVER = """
import os
import json
import socket
import sys
import uvicorn

class ReadyServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            os.write(int(sys.argv[2]), b"ready")
        os.close(int(sys.argv[2]))

try:
    listener = socket.socket(fileno=int(sys.argv[1]))
    ReadyServer(uvicorn.Config(
        "ac_platform.http.app:app", log_level="critical", access_log=False,
    )).run(sockets=[listener])
except Exception as error:
    diagnostic = {"type": type(error).__name__}
    if hasattr(error, "errors"):
        diagnostic["fields"] = [item["loc"] for item in error.errors()]
    os.write(int(sys.argv[2]), json.dumps(diagnostic).encode())
    os.close(int(sys.argv[2]))
    raise SystemExit(1)
"""


@pytest.fixture(scope="module")
def postgres_harness():
    for engine in _postgres_harness.__wrapped__():
        yield _Harness(engine=engine, schema_url=engine.url)


def require(condition: bool, case: str) -> None:
    if not condition:
        raise AssertionError(f"Candidate acceptance refused: {case}")


@contextmanager
def candidate_server(harness, settings):
    with socket.socket() as listener, tempfile.TemporaryDirectory() as working_directory:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        admin = f"http://127.0.0.1:{port}"
        member = f"http://localhost:{port}"
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "LANG", "LC_ALL", "VIRTUAL_ENV")
            if key in os.environ
        }
        environment.update(
            PYTHONPATH=str(ROOT / "packages/python"),
            PYTHONDONTWRITEBYTECODE="1",
            AC_ENVIRONMENT="test",
            AC_EXTERNAL_SIDE_EFFECTS_HOLD="true",
            AC_DATABASE_URL=harness.schema_url.render_as_string(hide_password=False),
            AC_OPERATIONS_TENANT_ID=str(settings.operations_tenant_id),
            AC_PUBLIC_LEARNER_TENANT_ID=str(settings.public_learner_tenant_id),
            AC_SESSION_TOKEN_PEPPER=settings.session_token_pepper.get_secret_value(),
            AC_OAUTH_TRANSACTION_SECRET=settings.oauth_transaction_secret.get_secret_value(),
            AC_EMAIL_CHALLENGE_SECRET=settings.email_challenge_secret.get_secret_value(),
            AC_LEARNER_CONSENT_VERSION=settings.learner_consent_version,
            AC_ADMIN_APP_URL=admin,
            AC_PUBLIC_APP_URL=f"http://127.0.0.3:{port}",
            AC_SALES_XRAY_APP_URL=member,
            AC_COACH_APP_URL=f"http://127.0.0.2:{port}",
            AC_API_URL=admin,
            AC_INTERNAL_API_HOST="127.0.0.4",
        )
        read_fd, write_fd = os.pipe()
        process = None
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed local candidate, disposable DB
                [sys.executable, "-c", SERVER, str(listener.fileno()), str(write_fd)],
                cwd=working_directory,
                env=environment,
                pass_fds=(listener.fileno(), write_fd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.close(write_fd)
            write_fd = -1
            readable, _, _ = fd_select.select([read_fd], [], [], 30)
            signal = os.read(read_fd, 4096) if readable else b""
            if signal != b"ready":
                # Only exception types and setting names, never the exception's
                # text, model inputs, logs or database URL, can leave the child.
                diagnostic = signal.decode(errors="replace")
                require(
                    False,
                    "runtime startup " + re.sub(r"[^A-Za-z0-9_\[\]{},:\" ]", "", diagnostic),
                )
            yield admin, member
        finally:
            os.close(read_fd)
            if write_fd != -1:
                os.close(write_fd)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                require(process.poll() is not None, "runtime shutdown")


def test_candidate_username_first_change_over_real_http(postgres_harness, tmp_path):
    receipt = {"scope": "local candidate API acceptance; not deployed UI or release acceptance"}
    cases = []

    def request(client, case, method, path, expected, **kwargs):
        response = client.request(method, path, **kwargs)
        require(response.status_code == expected, case)
        cases.append({"case": case, "status": response.status_code, "passed": True})
        return response

    async def journey():
        async with account(postgres_harness) as (
            _asgi_client,
            sessions,
            settings,
            tenant,
            _unused_account,
            operator,
            _unused_key,
        ):
            async with sessions() as database, database.begin():
                manager = uuid4()
                database.add(
                    Person(
                        id=manager,
                        email=f"{manager}@example.test",
                        email_verified_at=datetime.now(UTC),
                    )
                )
                await database.flush()
                database.add(
                    Membership(
                        tenant_id=settings.operations_tenant_id, person_id=manager, role="owner"
                    )
                )
                await database.flush()
                identity = AsyncIdentityApplication(
                    database, token_pepper=settings.session_token_pepper.get_secret_value()
                )
                manager_session = await identity.issue_authenticated_session(manager)
                operator_session = await identity.issue_authenticated_session(operator)
                capability = CapabilityApplication(
                    database, operations_tenant_id=settings.operations_tenant_id
                )
                await capability.bootstrap_first_manager(
                    person_id=manager, command_id=uuid4(), reason="Fictional TCP acceptance"
                )
                actor = (await identity.resolve_actor(manager_session.token)).actor
                await capability.grant(
                    actor,
                    command_id=uuid4(),
                    subject_person_id=operator,
                    permission="platform_organisations_manage",
                    scope=CapabilityScope("platform"),
                    reason="Fictional TCP issuer",
                )
            with (
                candidate_server(postgres_harness, settings) as (admin_origin, member_origin),
                httpx.Client(base_url=admin_origin, trust_env=False, timeout=15) as admin,
                httpx.Client(base_url=member_origin, trust_env=False, timeout=15) as member,
            ):
                request(member, "full runtime ready", "GET", "/health/ready", 200)
                headers = {
                    "Origin": admin_origin,
                    "Cookie": f"ac_session={operator_session.token}",
                    "Idempotency-Key": str(uuid4()),
                }
                path = f"/v1/platform/organisations/{tenant}/accounts"
                body = {
                    "username": f"tcp.rep.{uuid4().hex}",
                    "display_name": "Fictional TCP Rep",
                    "reason": "AUT-1694 candidate TCP acceptance",
                }
                issued = request(
                    admin,
                    "Admin once-copy issuance",
                    "POST",
                    path,
                    201,
                    headers=headers,
                    json=body,
                )
                require(
                    issued.headers.get("cache-control") == "private, no-store",
                    "private issuance",
                )
                account_payload = issued.json()
                temporary = account_payload["temporary_password"]
                require(
                    isinstance(temporary, str) and bool(temporary),
                    "original credential delivered",
                )
                replay = request(
                    admin, "Admin replay", "POST", path, 201, headers=headers, json=body
                )
                require(replay.json().get("temporary_password") is None, "replay has no credential")
                login_body = {"email": account_payload["username"], "password": temporary}
                member_headers = {"Origin": member_origin}
                login = request(
                    member,
                    "temporary login requires change",
                    "POST",
                    "/v1/auth/password/login",
                    200,
                    headers=member_headers,
                    json=login_body,
                )
                require(
                    login.json() == {"authenticated": False, "password_change_required": True},
                    "mandatory change response",
                )
                require(not member.cookies.get("ac_session"), "no session before change")
                request(member, "protected read before change", "GET", "/v1/me", 401)
                config = request(
                    member,
                    "current consent configuration",
                    "GET",
                    "/v1/auth/email-code/config?surface=sales_xray",
                    200,
                ).json()
                chosen = secrets.token_urlsafe(24)
                change_body = {
                    **login_body,
                    "new_password": chosen,
                    "consent": True,
                    "age_attested": True,
                    "consent_version": config["consent_version"],
                }
                changed = request(
                    member,
                    "mandatory first change",
                    "POST",
                    "/v1/auth/password/first-change",
                    200,
                    headers=member_headers,
                    json=change_body,
                )
                require(
                    changed.json().get("authenticated") is True
                    and bool(member.cookies.get("ac_session")),
                    "normal session after change",
                )
                me = request(member, "current member session", "GET", "/v1/me", 200).json()
                require(
                    me.get("selected_tenant_id") == str(tenant)
                    and me.get("email") is None
                    and me.get("email_verified_at") is None,
                    "honest organisation identity",
                )
                request(
                    member,
                    "organisation membership read",
                    "GET",
                    "/v1/organisation/members",
                    200,
                )
                request(
                    member,
                    "unapproved Sales Xray workspace stays gated",
                    "GET",
                    "/v1/me/sales-xray-profile",
                    403,
                )
                request(
                    member,
                    "normal logout",
                    "POST",
                    "/v1/auth/logout",
                    204,
                    headers=member_headers,
                )
                request(
                    member,
                    "consumed temporary password refuses",
                    "POST",
                    "/v1/auth/password/login",
                    401,
                    headers=member_headers,
                    json=login_body,
                )
                relogin = request(
                    member,
                    "chosen password signs in",
                    "POST",
                    "/v1/auth/password/login",
                    200,
                    headers=member_headers,
                    json={"email": account_payload["username"], "password": chosen},
                )
                require(relogin.json().get("authenticated") is True, "relogin authenticated")
                request(member, "session after chosen-password login", "GET", "/v1/me", 200)
                with Session(postgres_harness.engine) as database:
                    receipt["migration_head"] = database.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
                    require(
                        verify_audit_chain_sync(database, tenant_id=tenant).valid,
                        "append-only audit chain",
                    )
                    events = list(
                        database.scalars(
                            select(AuditEvent).where(
                                AuditEvent.resource_id == account_payload["person_id"]
                            )
                        )
                    )
                    require(
                        bool(events)
                        and all(
                            temporary not in str(event.payload) and chosen not in str(event.payload)
                            for event in events
                        ),
                        "audit credential secrecy",
                    )
                cases.append({"case": "audit chain and credential secrecy", "passed": True})
                receipt.update(
                    tenant_id=str(tenant),
                    person_id=account_payload["person_id"],
                    origin=member_origin,
                    admin_origin=admin_origin,
                )

    asyncio.run(journey())
    receipt.update(
        observed_at=datetime.now(UTC).isoformat(),
        runtime_head=subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - fixed local Git read
            cwd=ROOT,
            text=True,
        ).strip(),  # noqa: S603,S607 - fixed local Git read
        harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=cases,
        runtime_stopped=True,
        credentials_exported=False,
    )
    destination = Path(os.getenv("AC_USERNAME_CANDIDATE_RECEIPT", str(tmp_path / "receipt.json")))
    destination.write_text(json.dumps(receipt, indent=2) + "\n")
