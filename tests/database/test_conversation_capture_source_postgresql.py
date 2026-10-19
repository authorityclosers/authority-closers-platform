"""X-Capture-Source on the source upload (ADR 0056 F2) lands on the call's append-only row."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
    _sign_in,
    _wav_one_second_48k,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_postgres_upload_records_how_the_phone_captured_it(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            transport = httpx.ASGITransport(app=setup.app)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
                _sign_in(setup, client)
                data = _wav_one_second_48k()
                base = await _headers(client, data)

                unknown = await client.put(
                    f"{PREFIX}/submissions/{uuid4()}/source",
                    content=data,
                    headers={**base, "X-Capture-Source": "file_name_guess"},
                )
                assert unknown.status_code == 422

                tagged = uuid4()
                saved = await client.put(
                    f"{PREFIX}/submissions/{tagged}/source",
                    content=data,
                    headers={**base, "X-Capture-Source": "android_call_recorder"},
                )
                assert saved.status_code == 202, saved.text

                other = _wav_one_second_48k() + b"\0"
                plain = uuid4()
                untagged = await client.put(
                    f"{PREFIX}/submissions/{plain}/source",
                    content=other,
                    headers={
                        **(await _headers(client, other)),
                        "X-Source-SHA256": hashlib.sha256(other).hexdigest(),
                    },
                )
                assert untagged.status_code in (202, 422), untagged.text

            async with setup.sessions() as database:
                rows = dict(
                    (
                        await database.execute(
                            select(
                                ConversationGuestSubmission.submission_id,
                                ConversationGuestSubmission.capture_source,
                            ).where(ConversationGuestSubmission.submission_id.in_([tagged, plain]))
                        )
                    ).all()
                )
            assert rows[tagged] == "android_call_recorder"
            if plain in rows:
                assert rows[plain] is None
        finally:
            await setup.engine.dispose()

    run(exercise())
