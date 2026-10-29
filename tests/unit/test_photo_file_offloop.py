"""Photo bytes and image resizing never occupy the request thread."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from ac_platform.identity import person_photos as photos


async def test_read_photo_file_off_loop():
    main = threading.get_ident()
    database = AsyncMock()
    database.scalar.return_value = SimpleNamespace(
        storage_key="file", sha256="digest", photo=None, content_type="image/webp"
    )

    class Files:
        def read(self, key, *, sha256):
            assert threading.get_ident() != main
            assert (key, sha256) == ("file", "digest")
            return b"image"

    result = await photos.read_photo(database, uuid4(), Files())
    assert result.data == b"image" and result.sha256 == "digest"


async def test_photo_resize_off_loop(monkeypatch):
    main = threading.get_ident()

    def resize(data):
        assert threading.get_ident() != main
        return b"resized"

    keep = AsyncMock(return_value="url")
    monkeypatch.setattr(photos, "resized", resize)
    monkeypatch.setattr(photos, "_keep", keep)
    monkeypatch.setattr(photos, "_kind", lambda data: "image/png")
    await photos.save_upload(
        AsyncMock(),
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        content_type="image/png",
        data=b"image",
    )
    assert keep.await_args.kwargs["picture"] == b"resized"
