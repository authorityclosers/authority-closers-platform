"""Synthetic video uploads through real HTTP gates and disposable PostgreSQL.

These are application proofs, without Cloudflare, a hosted login or a provider.
The complete original MP4, including optional padding, must stay hash-bound.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence import signals
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.storage import CHUNK_BYTES
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.outbox.models import Job
from tests.database.test_bulk_import_postgresql import postgres_harness as _bulk_postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
    _sign_in,
)
from tests.database.test_conversation_worker_postgresql import _reconcile


@pytest.fixture
def postgres_harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    yield from _bulk_postgres_harness.__wrapped__(monkeypatch)


def synthetic_mp4(path: Path, *, sound: bool, target_bytes: int | None = None) -> bytes:
    command = [
        signals._tool("ffmpeg"),
        "-v",
        "error",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=128x72:r=1:d=1",
    ]
    if sound:
        command += [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:a",
            "aac",
            "-b:a",
            "32k",
        ]
    command += ["-c:v", "mpeg4", "-q:v", "15", "-threads", "1", "-f", "mp4", "-y", str(path)]
    subprocess.run(  # noqa: S603 -- fixed synthetic sources, no real voice
        command, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    if target_bytes is not None:
        with path.open("r+b") as stream:
            stream.seek(0, 2)
            remaining = target_bytes - stream.tell()
            assert remaining >= 8
            stream.write(remaining.to_bytes(4, "big") + b"free")
            stream.seek(target_bytes - 1)
            stream.write(b"\0")
    return path.read_bytes()


async def upload_frames(data: bytes) -> Any:
    # A single PUT streams bounded ASGI frames, as the HTTP server does.
    for offset in range(0, len(data), CHUNK_BYTES):
        yield data[offset : offset + CHUNK_BYTES]


@pytest.mark.parametrize("target_bytes", [None, 95_000_000, MAX_AUDIO_BYTES])
def test_video_upload_keeps_complete_source_and_exposes_the_real_local_stage(
    postgres_harness: Any, tmp_path: Path, target_bytes: int | None
) -> None:
    data = synthetic_mp4(tmp_path / "source.mp4", sound=True, target_bytes=target_bytes)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                policy = await client.get(PREFIX + "/upload-policy")
                assert policy.status_code == 200
                assert policy.json()["maximum_file_bytes"] == MAX_AUDIO_BYTES
                submission = uuid4()
                path = f"{PREFIX}/submissions/{submission}"
                uploaded = await client.put(
                    path + "/source",
                    content=upload_frames(data),
                    headers={**await _headers(client, data), "Content-Length": str(len(data))},
                )
                assert uploaded.status_code == 202, uploaded.text
                result = uploaded.json()
                digest = hashlib.sha256(data).hexdigest()
                assert result["source_sha256"] == digest
                assert 900 <= result["duration_ms"] <= 1200
                recording_id = UUID(result["recording_id"])
                async with setup.sessions() as db:
                    recording = await db.get(ConversationRecording, recording_id)
                    assert recording.content_type == "video/mp4"
                    assert recording.source_bytes == len(data)
                    assert recording.source_sha256 == digest
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == submission
                        )
                    )
                    assert usage.source_sha256 == digest and usage.reserved_seconds == 2
                await _reconcile(setup.sessions, setup.state)
                worker = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await worker.run_once()
                progress = await client.get(path)
                assert progress.status_code == 200, progress.text
                assert progress.json()["source_sha256"] == digest
                assert progress.json()["local_state"] == "completed"
                assert progress.json()["has_report"] is False
                assert (await client.get(path + "/report")).status_code == 404
                async with setup.sessions() as db:
                    checkpoint = await db.scalar(
                        select(ConversationCheckpoint).where(
                            ConversationCheckpoint.recording_id == recording_id,
                            ConversationCheckpoint.stage == "C1",
                        )
                    )
                    assert checkpoint.payload["source_sha256"] == digest
                    assert checkpoint.payload["source_bytes"] == len(data)
                    assert checkpoint.payload["media_duration_ms"] == result["duration_ms"]
                    assert (
                        await db.scalar(select(func.count()).select_from(ConversationInferenceTask))
                        == 0
                    )
                    assert (
                        await db.scalar(
                            select(func.count()).select_from(Job).where(Job.external_side_effect)
                        )
                        == 0
                    )
                # Check source bytes after both actual native decodes, including
                # all original media and padding, without loading another copy.
                assert signals.file_sha256(tmp_path / "source.mp4") == digest
                assert not list(setup.runtime.scratch.root.glob("**/*.media"))
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_video_without_sound_is_clear_and_never_reserves_or_enqueues(
    postgres_harness: Any, tmp_path: Path
) -> None:
    data = synthetic_mp4(tmp_path / "silent.mp4", sound=False)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                path = f"{PREFIX}/submissions/{uuid4()}"
                response = await client.put(
                    path + "/source", content=data, headers=await _headers(client, data)
                )
                assert response.status_code == 422, response.text
                assert response.json()["detail"] == "This file has no sound track."
                assert setup.native.calls == 0
                assert (await client.get(path)).status_code == 404
                async with setup.sessions() as db:
                    for model in (ConversationAcquisitionUsage, ConversationRecording, Job):
                        assert await db.scalar(select(func.count()).select_from(model)) == 0
                assert not list(setup.runtime.scratch.root.glob("**/*.media"))
        finally:
            await setup.engine.dispose()

    run(exercise())
