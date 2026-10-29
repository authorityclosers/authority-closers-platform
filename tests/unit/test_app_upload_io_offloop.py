"""Integration uploads retain digest checks while filesystem work stays off-loop."""

import builtins
import hashlib
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from starlette.requests import Request

from ac_platform.integrations import app_uploads as uploads


@pytest.mark.parametrize("valid_digest", [True, False])
async def test_upload_files_off_loop_and_bad_digest_cleans_up(tmp_path, monkeypatch, valid_digest):
    main = threading.get_ident()
    file_threads = []
    original_open = builtins.open

    def open_file(path, *args, **kwargs):
        file_threads.append(threading.get_ident())
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_file)
    body = b"synthetic recording bytes"
    digest = hashlib.sha256(body).hexdigest() if valid_digest else "0" * 64
    headers = {
        "content-length": str(len(body)),
        "content-type": "application/octet-stream",
        "x-source-sha256": digest,
        "x-external-id": "test-upload",
        "x-recording-consent": uploads.CONSENT,
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        },
        receive,
    )
    database = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
        add=Mock(),
        flush=AsyncMock(),
    )

    @asynccontextmanager
    async def transaction():
        yield database

    database.begin = transaction
    monkeypatch.setattr(uploads, "AuditRepository", lambda db: SimpleNamespace(append=AsyncMock()))

    async def run():
        return await uploads.receive(
            request,
            transaction,
            root=tmp_path,
            tenant_id=uuid4(),
            person_id=uuid4(),
            grant_id=uuid4(),
            app_label="test",
            lead_ok=AsyncMock(),
            base=None,
        )

    if valid_digest:
        result, status = await run()
        assert status == 202
        files = list(tmp_path.rglob("*.bin"))
        assert len(files) == 1
        with original_open(files[0], "rb") as stored:
            assert stored.read() == body
    else:
        with pytest.raises(uploads.UploadRefused, match="SHA-256"):
            await run()
        assert not list(tmp_path.rglob("*.part-*"))
        assert not list(tmp_path.rglob("*.bin"))
    assert file_threads and all(ident != main for ident in file_threads)
