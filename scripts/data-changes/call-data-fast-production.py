"""AUT-2182: fast ON at Rs150/day, deep OFF, streaming OFF via Admin's handler.

Run in the deployed API container. Dry-run by default; --apply commits one
transaction. Uses the named control account's current canonical Admin session,
never its token, matching the established production operator scripts. The
handler still checks current identity, membership, Admin host, origin, settings
revision and appends its normal audit. An additional audit pins the owner order.
Take a production snapshot before applying. Rollback the runner by disabling
ac-call-data@production; do not erase settings or run history.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from starlette.requests import Request

DATA_CHANGE = "scripts/data-changes/call-data-fast-production.py"
ORDER_ACTION = "call_data.production_fast_order"


class Refused(RuntimeError):
    pass


@dataclass(frozen=True)
class Command:
    control_email: str
    apply: bool = False


def desired(config: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(config)
    result["fast"]["enabled"] = True
    result["fast"]["daily_cap_inr"] = 150
    result["deep"]["enabled"] = False
    result["streaming"]["provider"] = "off"
    return result


async def execute(db: Any, command: Command, settings: Any) -> dict[str, Any]:
    import httpx
    from fastapi import FastAPI

    from ac_platform.audit.service import AuditRepository
    from ac_platform.call_data.admin_http import install_call_data_admin_http
    from ac_platform.conversation_intelligence.provider_admin import CONTROL_ACCOUNTS
    from ac_platform.http.routes import RouteContext
    from ac_platform.identity.models import Person, Session
    from ac_platform.kernel.authz import ActorContext

    email = command.control_email.strip().casefold()
    if email not in CONTROL_ACCOUNTS:
        raise Refused("control_account_required")
    if settings.operations_tenant_id is None:
        raise Refused("operations_workspace_required")
    person = await db.scalar(select(Person).where(Person.email.ilike(email)))
    if person is None:
        raise Refused("control_account_not_found")
    session = await db.scalar(
        select(Session)
        .where(
            Session.person_id == person.id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
            Session.selected_tenant_id == settings.operations_tenant_id,
        )
        .order_by(Session.created_at.desc())
        .limit(1)
    )
    if session is None:
        raise Refused("current_admin_session_required")
    actor = ActorContext(
        person_id=person.id,
        session_id=session.id,
        tenant_id=settings.operations_tenant_id,
        permissions=frozenset({"admin_surface"}),
    )
    # These are the only transaction fields used by this area's existing handler.
    auth = SimpleNamespace(database=db, resolved=SimpleNamespace(actor=actor))
    app = FastAPI()

    async def current_session(_request: Request):
        yield auth

    install_call_data_admin_http(app, RouteContext(settings, current_session, None))
    origin = str(settings.admin_app_url).rstrip("/")

    async def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=origin
        ) as client:
            response = await client.request(method, path, headers={"Origin": origin}, **kwargs)
        if response.status_code != 200:
            raise Refused(f"admin_route_refused_{response.status_code}")
        return response.json()

    # Admission is checked even on a no-op. Never expose recent call metadata.
    before = await request("GET", "/v1/admin/call-data")
    target = desired(before["config"])
    result = {
        "environment": settings.environment,
        "release_id": settings.release_id,
        "before": {"config": before["config"], "revision": before["revision"]},
    }
    if before["config"] == target:
        return {**result, "status": "no_op", "after": result["before"]}
    saved = await request(
        "PUT",
        "/v1/admin/call-data/settings",
        json={"expected_revision": before["revision"], "config": target},
    )
    await AuditRepository(db).append_for_actor(
        actor,
        action=ORDER_ACTION,
        resource_type="call_data_settings",
        resource_id=str(saved["revision"]),
        payload={
            "approver": "Suyash (owner), relayed by Align 3, 21 Oct 2026 15:05Z",
            "issue": "AUT-2182",
            "root_authority": "AUT-63",
            "data_change": DATA_CHANGE,
            "operator": "Root Operator",
            "release_id": settings.release_id,
            "order": (
                "Install fast call-data on production, Rs150/day; deep off; live transcription off"
            ),
            "before_revision": before["revision"],
            "after_revision": saved["revision"],
        },
    )
    after = await request("GET", "/v1/admin/call-data")
    if after["config"] != target:
        raise Refused("settings_readback_mismatch")
    return {
        **result,
        "status": "applied" if command.apply else "dry_run",
        "after": {"config": after["config"], "revision": after["revision"]},
    }


class DryRun(Exception):
    pass


async def run(command: Command, settings: Any) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            try:
                async with db.begin():
                    result = await execute(db, command, settings)
                    if not command.apply:
                        raise DryRun
            except DryRun:
                pass
        return result
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--control-email", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        from ac_platform.application.release_identity import require_baked_release_id
        from ac_platform.application.settings import Settings

        settings = Settings(_env_file=None)
        if settings.environment != "production" or not args.allow_production:
            raise Refused("explicit_production_only")
        require_baked_release_id(settings.release_id)
        if settings.release_id != args.expected_release:
            raise Refused("release_mismatch")
        result = asyncio.run(run(Command(args.control_email, args.apply), settings))
    except Refused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
