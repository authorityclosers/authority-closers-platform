"""Fictional narration export: live admission, review revocation and byte ranges."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest

from ac_platform.coaching import placeholder
from ac_platform.coaching.dataset import read_topics
from ac_platform.tenancy.models import Tenant
from tests.database.test_coaching_postgresql import draft_for, install
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call
from tests.unit.coaching.test_dataset import AUDIO, topic


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_reviewed_placeholder_clips_same_request_and_private_source(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    async def exercise() -> None:
        root = tmp_path / "coaching-media"
        root.mkdir()
        record = topic(root)
        monkeypatch.setattr("ac_platform.coaching.http.read_topics", lambda: read_topics(root))
        monkeypatch.setattr("ac_platform.coaching.http.DATASET_ROOT", root)
        # Reviewed exports only here; the packaged placeholders have their own test.
        monkeypatch.setattr("ac_platform.coaching.placeholder.clips_for", lambda _skill: ())
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        try:
            call = await direct_call(setup)
            await draft_for(setup, call, dimension_evidence=True)
            review_id = record.current_reviews[0].review_id
            source = (
                f"/v1/me/coaching/media/{record.topic_id}/"
                f"{record.transcript.sha256}/{review_id}/source"
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                assert (await client.get(source)).status_code == 401
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                result = await client.get(f"/v1/me/coaching/calls/{call}")
                assert result.status_code == 200, result.text
                my_result = await client.get("/v1/me/coaching")
                assert my_result.status_code == 200, my_result.text
                assert my_result.json()["media_clips"][0]["topic_id"] == record.topic_id
                clip = result.json()["media_clips"][0]
                assert clip["topic_id"] == record.topic_id and clip["placeholder"] is True
                assert clip["access"] == "full" and "relative_path" not in clip
                media = await client.get(source, headers={"Range": "bytes=4-12"})
                assert media.status_code == 206 and media.content == AUDIO[4:13]
                assert media.headers["cache-control"] == "private, no-store"
                assert media.headers["content-length"] == "9"
                assert (
                    await client.get(source, headers={"Range": "bytes=1-2,4-6"})
                ).status_code == 416
                assert (await client.get(source, params={"plan": "unlimited"})).status_code == 422
                assert (await client.get("https://admin.example.test" + source)).status_code == 404
                assert (
                    await client.get(source.replace(str(review_id), str(UUID(int=999))))
                ).status_code == 404
                assert (
                    await client.get(source.replace(record.transcript.sha256, "f" * 64))
                ).status_code == 404
                (root / record.narration.relative_path).write_bytes(b"x" * len(AUDIO))
                changed = await client.get(source)
                assert changed.status_code == 404 and AUDIO not in changed.content
                (root / record.narration.relative_path).write_bytes(AUDIO)
                revoked = record.model_copy(
                    update={
                        "current_reviews": (
                            record.current_reviews[0].model_copy(update={"decision": "reject"}),
                        )
                    }
                )
                (root / f"{record.topic_id}.json").write_text(
                    revoked.model_dump_json(by_alias=True)
                )
                assert (await client.get(source)).status_code == 404
                assert (await client.get(f"/v1/me/coaching/calls/{call}")).json()[
                    "media_clips"
                ] == []
                (root / f"{record.topic_id}.json").write_text(record.model_dump_json(by_alias=True))
                async with setup.sessions() as database, database.begin():
                    tenant = await database.get(Tenant, setup.state.tenant_id)
                    tenant.status = "suspended"
                denied = await client.get(source)
                assert denied.status_code in {401, 403} and AUDIO not in denied.content
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_packaged_placeholders_free_lesson_streams_and_locked_lesson_never_does(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    async def exercise() -> None:
        monkeypatch.setattr("ac_platform.coaching.http.read_topics", lambda: ())
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        try:
            call = await direct_call(setup)
            await draft_for(setup, call, dimension_evidence=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                result = await client.get(f"/v1/me/coaching/calls/{call}")
                assert result.status_code == 200, result.text
                free, locked = result.json()["media_clips"]
                assert free["access"] == "full" and free["topic_id"].startswith("syn-coach-")
                assert locked["access"] == "locked" and locked["offer"]["academy"]
                assert "relative_path" not in free and "audio_sha256" not in free

                def source(clip: dict[str, Any]) -> str:
                    return (
                        f"/v1/me/coaching/media/{clip['topic_id']}/{clip['revision']}/"
                        f"{clip['review_id']}/source"
                    )

                audio = (placeholder.MEDIA / f"{free['topic_id']}.mp3").read_bytes()
                media = await client.get(source(free), headers={"Range": "bytes=0-9"})
                assert media.status_code == 206 and media.content == audio[:10]
                assert media.headers["cache-control"] == "private, no-store"
                assert (await client.get(source(locked))).status_code == 404
                client.cookies.clear()
                assert (await client.get(source(free))).status_code == 401
        finally:
            await setup.engine.dispose()

    run(exercise())
