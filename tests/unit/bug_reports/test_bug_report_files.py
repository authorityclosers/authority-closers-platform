"""Files that follow an advanced bug report (screenshots.clean_file, 0149): pictures are
re-encoded, recordings kept once their container checks out, PDFs kept, text scrubbed line by
line, anything else refused."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from ac_platform.bug_reports.screenshots import ScreenshotError, clean_file
from ac_platform.bug_reports.scrub import clean_advanced, scrub_block


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (320, 200), (200, 40, 40)).save(output, format="JPEG")
    return output.getvalue()


def test_each_kind_of_file_is_cleaned_or_refused() -> None:
    picture = clean_file(_jpeg(), "image/jpeg")
    assert (picture.content_type, picture.ending) == ("image/webp", "webp")
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
    assert clean_file(webm, "video/webm").data == webm
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    assert clean_file(mp4, "video/mp4").ending == "mp4"
    assert clean_file(b"%PDF-1.7 fictional", "application/pdf").ending == "pdf"
    log = clean_file(b"line for asha@example.test\ntoken=abc123\n", "text/plain")
    assert log.data == b"line for [email]\n[secret]"
    for body, content_type in (
        (b"not a webm", "video/webm"),
        (b"MZ not an mp4", "video/mp4"),
        (b"not a pdf", "application/pdf"),
        (b"\xff\xfe broken text", "text/plain"),
        (b"#!/bin/sh", "application/x-sh"),
        (b"", "text/plain"),
    ):
        with pytest.raises(ScreenshotError):
            clean_file(body, content_type)


def test_a_log_keeps_its_lines() -> None:
    assert scrub_block("a\nBearer abcdefghijklmnop\n\nc") == "a\nBearer [token]\n\nc"


def test_the_advanced_parts_are_bounded() -> None:
    assert clean_advanced("nope") is None
    parts = clean_advanced(
        {
            "steps": ["One"] * 30,
            "comments": [{"n": number} for number in range(1, 30)],
            "files": 99,
            "marked": "yes",
        }
    )
    assert parts is not None
    assert len(parts["steps"]) == 20 and len(parts["comments"]) == 20
    assert parts["files"] == 0 and parts["marked"] is False
    assert parts["comments"][0] == {
        "n": 1,
        "note": "",
        "selector": "",
        "components": [],
        "on_picture": False,
    }
