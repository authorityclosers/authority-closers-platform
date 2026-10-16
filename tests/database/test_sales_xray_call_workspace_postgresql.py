"""A saved-call link opens in the workspace that holds the call (owner, 16 Oct).

On another device the person may have another workspace selected; the call
page asks which of their workspaces holds the call and switches to it. The
answer names only a workspace the person belongs to and may read the call in.
Synthetic one-second WAV upload; no provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from ac_platform.http.sales_xray_workspaces import install_sales_xray_workspaces_http
from tests.database.test_conversation_account_library_postgresql import _upload
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_call_workspace_names_only_the_readers_own_workspace(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        # The harness tenant is the person's Personal workspace.
        install_sales_xray_workspaces_http(
            setup.app,
            settings=setup.settings,
            require_actor=setup.require_actor,
            intake=setup.runtime,
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                submission = (await _upload(client))["submission_id"]
                path = "/v1/me/sales-xray-workspaces/call/"
                found = await client.get(path + submission)
                assert found.status_code == 200, found.text
                assert found.json() == {"tenant_id": str(setup.state.tenant_id)}
                assert "no-store" in found.headers["cache-control"]
                # Unknown calls and extra parameters say nothing.
                assert (await client.get(path + str(uuid4()))).status_code == 404
                assert (await client.get(path + submission + "?x=1")).status_code != 200
                # Signed out: no answer at all.
                client.cookies.clear()
                assert (await client.get(path + submission)).status_code in {401, 403}
        finally:
            await setup.engine.dispose()

    run(exercise())
