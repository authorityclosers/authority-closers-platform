"""Each member's profile (owner, 25 Oct 2026: a photo, a user id and the details, "so the
business owner can identify who did what work"): the user id's rules, title and team,
the completion progress, the photo upload's rules, and whose photo wins."""

from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from ac_platform.identity import person_photos
from ac_platform.identity.google_profile_models import PersonGoogleProfile
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileHandleTaken,
    erase_sales_xray_profile,
    get_sales_xray_profile,
    update_profile_details,
)
from ac_platform.identity.sales_xray_profile_models import PersonPhoto
from tests.unit.identity.test_sales_xray_profile import (  # noqa: F401
    NOW,
    OTHER_PERSON_ID,
    PERSON_ID,
    SESSION_ID,
    TENANT_ID,
    _AuditRecorder,
    database,
)


def _image(kind: str, colour: tuple[int, int, int], size: tuple[int, int] = (40, 30)) -> bytes:
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", size, colour).save(output, format=kind)
    return output.getvalue()


WEBP = _image("WEBP", (200, 30, 30))
PNG = _image("PNG", (30, 30, 200), (30, 60))


async def _details(db: Any, person=PERSON_ID, *, revision=0, now=NOW, **fields: Any) -> Any:
    values = {"handle": None, "title": None, "team": None, **fields}
    return await update_profile_details(
        db,
        person_id=person,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        expected_revision=revision,
        now=now,
        **values,
    )


@pytest.mark.asyncio
async def test_user_id_title_and_team_with_progress(database: Any) -> None:  # noqa: F811
    db, _ = database
    saved = await _details(db, handle="@Rahul.E", title="  Sales   manager ", team="Inside sales")
    assert (saved.handle, saved.title, saved.team) == ("rahul.e", "Sales manager", "Inside sales")
    assert saved.completion == {"done": 4, "total": 6, "missing": ["photo", "phone"]}
    (event,) = _AuditRecorder.events
    assert event["action"] == "sales_xray.profile.details_updated.v1"
    assert event["payload"] == {"revision": 1, "changed_fields": ["handle", "title", "team"]}
    assert "rahul" not in str(event)  # field names, never values
    # Empty clears a title; a null user id keeps it.
    cleared = await _details(db, revision=1, title="", team="Inside sales")
    assert cleared.handle == "rahul.e" and cleared.title is None


@pytest.mark.asyncio
@pytest.mark.parametrize("handle", ["ab", "-rahul", "rahul e", "r" * 31, "admin", "Support"])
async def test_user_id_rules(database: Any, handle: str) -> None:  # noqa: F811
    db, _ = database
    with pytest.raises(ValueError):
        await _details(db, handle=handle)


@pytest.mark.asyncio
async def test_a_user_id_is_one_persons_and_changes_once_a_month(database: Any) -> None:  # noqa: F811
    db, _ = database
    await _details(db, handle="rahul.e")
    with pytest.raises(SalesXrayProfileHandleTaken, match="taken"):
        await _details(db, OTHER_PERSON_ID, handle="Rahul.E")
    with pytest.raises(SalesXrayProfileHandleTaken, match="again on"):
        await _details(db, revision=1, handle="rahul.x", now=NOW + timedelta(days=29))
    later = await _details(db, revision=1, handle="rahul.x", now=NOW + timedelta(days=31))
    assert later.handle == "rahul.x"


@pytest.mark.asyncio
async def test_the_photo_upload_rules_and_which_photo_wins(database: Any) -> None:  # noqa: F811
    db, sync = database
    for content_type, data, words in (
        ("image/gif", b"GIF89a", "JPEG, PNG or WebP"),
        ("image/png", WEBP, "JPEG, PNG or WebP"),  # the bytes decide, not the header
        ("image/webp", b"", "2 MB"),
        ("image/webp", WEBP + b"x" * person_photos.MAX_BYTES, "2 MB"),
    ):
        with pytest.raises(person_photos.PhotoRejected, match=words):
            await person_photos.save_upload(
                db,
                person_id=PERSON_ID,
                session_id=SESSION_ID,
                tenant_id=TENANT_ID,
                content_type=content_type,
                data=data,
            )
    # Google's photo first; an upload wins over it.
    sync.add(
        PersonGoogleProfile(
            person_id=OTHER_PERSON_ID,
            photo_jpeg=b"\xff\xd8\xff fictional",
            photo_sha256="b" * 64,
            claims_updated_at=NOW,
        )
    )
    sync.flush()
    url = await person_photos.save_upload(
        db,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        content_type="image/webp; charset=binary",
        data=WEBP,
    )
    urls = await person_photos.photo_urls(db, [PERSON_ID, OTHER_PERSON_ID, None])
    assert urls[PERSON_ID] == url and url.startswith(f"/v1/people/{PERSON_ID}/photo?v=")
    assert urls[OTHER_PERSON_ID] == f"/v1/people/{OTHER_PERSON_ID}/photo?v=bbbbbbbb"
    photo = await person_photos.read_photo(db, PERSON_ID)
    # Resized on the server: a 256 px WebP, whatever came in.
    assert photo is not None and photo.content_type == "image/webp"
    assert photo.data.startswith(b"RIFF") and photo.data[8:12] == b"WEBP"
    mine = await get_sales_xray_profile(db, person_id=PERSON_ID)
    assert mine.avatar_url == url and mine.own_photo and "photo" not in mine.missing
    assert mine.photo_url == "/v1/me/sales-xray-profile/photo"
    # A second photo replaces the first; removing it leaves initials.
    second = await person_photos.save_upload(
        db,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        content_type="image/png",
        data=PNG,
    )
    assert second != url and sync.get(PersonPhoto, PERSON_ID).revision == 2
    assert await person_photos.remove_upload(
        db, person_id=PERSON_ID, session_id=SESSION_ID, tenant_id=TENANT_ID
    )
    assert (await person_photos.photo_urls(db, [PERSON_ID]))[PERSON_ID] is None
    gone = await get_sales_xray_profile(db, person_id=PERSON_ID)
    assert (gone.avatar_url, gone.own_photo, gone.missing[0]) == (None, False, "photo")


@pytest.mark.asyncio
async def test_account_deletion_takes_the_photo(database: Any) -> None:  # noqa: F811
    db, sync = database
    await person_photos.save_upload(
        db,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        content_type="image/webp",
        data=WEBP,
    )
    assert await erase_sales_xray_profile(db, person_id=PERSON_ID)
    assert sync.get(PersonPhoto, PERSON_ID) is None


@pytest.mark.asyncio
async def test_a_photo_is_a_resized_file_and_an_unreadable_one_is_refused(
    database: Any,  # noqa: F811
    tmp_path: Path,
) -> None:
    """v0.93: a 256 px WebP file under the store, the bytes column as the fallback."""
    from PIL import Image

    db, sync = database
    files = person_photos.PhotoFiles(tmp_path)
    with pytest.raises(person_photos.PhotoRejected, match="could not be read"):
        await person_photos.save_upload(
            db,
            person_id=PERSON_ID,
            session_id=SESSION_ID,
            tenant_id=TENANT_ID,
            content_type="image/webp",
            data=b"RIFF\x10\x00\x00\x00WEBPVP8 fictional",
            files=files,
        )
    await person_photos.save_upload(
        db,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        content_type="image/png",
        data=_image("PNG", (10, 120, 60), (900, 400)),
        files=files,
    )
    row = sync.get(PersonPhoto, PERSON_ID)
    assert row.storage_key == f"person-photos/{PERSON_ID.hex}.1.webp" and row.photo is None
    stored = tmp_path / row.storage_key
    with Image.open(stored) as picture:
        assert picture.size == (256, 256) and picture.format == "WEBP"
    photo = await person_photos.read_photo(db, PERSON_ID, files)
    assert photo is not None and photo.data == stored.read_bytes()
    # A second photo replaces the first file.
    await person_photos.save_upload(
        db,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        content_type="image/webp",
        data=WEBP,
        files=files,
    )
    assert not stored.exists()
    assert (tmp_path / f"person-photos/{PERSON_ID.hex}.2.webp").exists()
