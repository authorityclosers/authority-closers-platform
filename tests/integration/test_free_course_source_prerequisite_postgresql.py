"""PostgreSQL proof for the audited source prerequisite operator command."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.catalog import cli as catalog_cli
from ac_platform.catalog.models import CatalogScope, ModulePrerequisite
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import (  # noqa: F401
    postgres_harness,
)


@pytest.mark.usefixtures("postgres_harness")
def test_source_prerequisite_apply_replay_and_wrong_scope_rollback(postgres_harness) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        tenant_id, actor_id, session_id = uuid4(), uuid4(), uuid4()
        program_id, version_id = uuid4(), uuid4()
        module_ids = [uuid4() for _ in range(4)]
        command_id = uuid4()
        session_token = "A" * 43
        session_pepper = b"local-session-token-pepper-change-before-production"
        try:
            async with sessions() as database, database.begin():
                database.add(
                    Tenant(id=tenant_id, slug=f"source-{tenant_id.hex}", name="Source tenant")
                )
                database.add(
                    Person(
                        id=actor_id,
                        email=f"owner-{actor_id.hex}@example.test",
                        email_verified_at=datetime.now(UTC),
                    )
                )
                await database.flush()
                database.add(Membership(tenant_id=tenant_id, person_id=actor_id, role="owner"))
                await database.flush()
                database.add(
                    IdentitySession(
                        id=session_id,
                        person_id=actor_id,
                        selected_tenant_id=tenant_id,
                        token_hash=hmac.new(
                            session_pepper, session_token.encode("ascii"), hashlib.sha256
                        ).digest(),
                        created_at=datetime.now(UTC),
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
                await database.flush()

                def seed(sync):
                    catalog = CatalogService(
                        SqlAlchemyCatalogStore(sync), clock=lambda: datetime.now(UTC)
                    )
                    program = catalog.create_program(
                        tenant_id=tenant_id,
                        scope=CatalogScope.TENANT,
                        program_id=program_id,
                        slug=f"source-{program_id.hex}",
                        title="Reviewed source",
                    )
                    version = catalog.create_version(
                        program.id,
                        tenant_id=tenant_id,
                        version_id=version_id,
                    )
                    modules = tuple(
                        catalog.add_module(
                            version.id,
                            tenant_id=tenant_id,
                            module_id=module_id,
                            position=position,
                            title=f"Module {position}",
                        )
                        for position, module_id in enumerate(module_ids, start=1)
                    )
                    return SimpleNamespace(
                        program_id=program.id,
                        version_id=version.id,
                        modules=modules,
                    )

                await database.run_sync(seed)
            environment = {
                "AC_DATABASE_URL": postgres_harness.schema_url.render_as_string(
                    hide_password=False
                ),
                "AC_ENVIRONMENT": "test",
                "AC_OPERATIONS_TENANT_ID": str(tenant_id),
            }

            def command(
                *,
                requested_program_id,
                module_id,
                prerequisite_module_id,
                requested_command_id,
                reason,
            ):
                return catalog_cli._parser().parse_args(  # noqa: SLF001 - actual CLI proof
                    [
                        "wire-prerequisite",
                        "--environment",
                        "test",
                        "--program-id",
                        str(requested_program_id),
                        "--program-version-id",
                        str(version_id),
                        "--module-id",
                        str(module_id),
                        "--prerequisite-module-id",
                        str(prerequisite_module_id),
                        "--command-id",
                        str(requested_command_id),
                        "--reason",
                        reason,
                    ]
                )

            with (
                patch.dict(os.environ, environment, clear=False),
                patch.object(catalog_cli, "_read_session_token", lambda: session_token),
            ):
                applied = await catalog_cli._execute(  # noqa: SLF001 - actual CLI proof
                    command(
                        requested_program_id=program_id,
                        module_id=module_ids[1],
                        prerequisite_module_id=module_ids[0],
                        requested_command_id=command_id,
                        reason="Isolated reviewed source graph",
                    )
                )
                assert applied["status"] == "applied"
                edge_id = applied["prerequisite_id"]

                replayed = await catalog_cli._execute(  # noqa: SLF001 - actual CLI proof
                    command(
                        requested_program_id=program_id,
                        module_id=module_ids[1],
                        prerequisite_module_id=module_ids[0],
                        requested_command_id=command_id,
                        reason="Different retry reason is ignored by receipt replay",
                    )
                )
                assert replayed["status"] == "replayed"
                assert replayed["prerequisite_id"] == edge_id

                wrong_scope_command = uuid4()
                with pytest.raises(catalog_cli.FreeCourseCliError, match="unexpected"):
                    await catalog_cli._execute(  # noqa: SLF001 - actual CLI proof
                        command(
                            requested_program_id=uuid4(),
                            module_id=module_ids[2],
                            prerequisite_module_id=module_ids[1],
                            requested_command_id=wrong_scope_command,
                            reason="This must roll back",
                        )
                    )

            async with sessions() as database, database.begin():
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ModulePrerequisite)
                        .where(ModulePrerequisite.tenant_id == tenant_id)
                    )
                    == 1
                )
                assert await database.get(AuditEvent, wrong_scope_command) is None
                assert (
                    await database.run_sync(lambda sync: verify_audit_chain_sync(sync, tenant_id))
                ).valid
        finally:
            await engine.dispose()

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(run())
    else:
        asyncio.run(run())
