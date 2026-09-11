"""Offline contracts for the local Studio video preview browser proof."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prove-local-studio-video-preview.py"
COACH_ORIGIN = "http://coach.localhost:3102"
PROGRAM_ID = "11111111-1111-4111-8111-111111111111"
ASSET_ID = "22222222-2222-4222-8222-222222222222"
VERSION_ID = "33333333-3333-4333-8333-333333333333"
PREFIX = f"/v1/admin/studio/programs/{PROGRAM_ID}"
UPLOAD = re.compile(re.escape(PREFIX) + r"/video-uploads(?:/[0-9a-f-]{36}/(?:bytes|complete))?$")


@pytest.fixture(scope="module")
def proof_script():
    spec = importlib.util.spec_from_file_location("studio_video_preview_proof", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, url: str, *, status: int, headers: dict[str, str], method: str = "GET"):
        self.url = url
        self.status = status
        self.headers = headers
        self.request = SimpleNamespace(method=method)


def _descriptor_url(query: str = "") -> str:
    return f"{COACH_ORIGIN}{PREFIX}/videos/{ASSET_ID}/versions/{VERSION_ID}/preview{query}"


def _bytes_url() -> str:
    return f"{_descriptor_url()}/bytes"


def _valid_descriptor(proof_script):
    return proof_script._preview_response_record(
        FakeResponse(
            _descriptor_url(),
            status=200,
            headers={
                "content-type": "application/json; charset=utf-8",
                "content-length": "246",
                "cache-control": "no-store",
            },
        ),
        PREFIX,
    )


def _valid_bytes(proof_script):
    return proof_script._preview_response_record(
        FakeResponse(
            _bytes_url(),
            status=206,
            headers={
                "content-type": "video/mp4",
                "content-length": "4096",
                "content-range": "bytes 0-4095/8192",
                "accept-ranges": "bytes",
                "cache-control": "private, no-store",
            },
        ),
        PREFIX,
    )


@pytest.mark.parametrize(
    ("url", "method", "kind", "path"),
    [
        (
            "https://external.example.test/publish?token=secret",
            "POST",
            "external",
            "/publish",
        ),
        (
            f"{COACH_ORIGIN}{PREFIX}/publish?token=secret",
            "POST",
            "blocked_write",
            f"{PREFIX}/publish",
        ),
    ],
)
def test_request_guard_denials_are_sanitized_and_classified(proof_script, url, method, kind, path):
    allowed, denied_kind = proof_script._request_decision(
        url,
        method,
        coach_origin=COACH_ORIGIN,
        permitted_upload=UPLOAD,
    )
    assert not allowed and denied_kind == kind
    record = proof_script._sanitized_request_record(url, method, denied_kind)
    assert record == {"kind": kind, "method": method, "path": path}
    assert "secret" not in str(record)
    allowed, denied_kind = proof_script._request_decision(
        f"{COACH_ORIGIN}{PREFIX}/video-uploads",
        "POST",
        coach_origin=COACH_ORIGIN,
        permitted_upload=UPLOAD,
    )
    assert allowed and denied_kind is None


def test_denied_or_external_request_fails_the_proof(proof_script):
    with pytest.raises(proof_script.shared.ProofFailure, match="external_request_was_attempted"):
        proof_script._assert_network_scope(
            [], [{"kind": "external", "method": "GET", "path": "/tracking"}]
        )
    with pytest.raises(proof_script.shared.ProofFailure, match="unapproved_write_was_attempted"):
        proof_script._assert_network_scope(
            [{"kind": "blocked_write", "method": "POST", "path": "/publish"}], []
        )


def test_preview_evidence_requires_exact_paths_and_private_media_headers(proof_script):
    descriptor = _valid_descriptor(proof_script)
    bytes_response = _valid_bytes(proof_script)
    assert descriptor is not None and descriptor["kind"] == "descriptor"
    assert bytes_response is not None and bytes_response["kind"] == "bytes"
    proof_script._assert_preview_responses([descriptor, bytes_response])

    unexpected = proof_script._preview_response_record(
        FakeResponse(
            _descriptor_url("?token=secret"),
            status=200,
            headers={"content-type": "application/json", "cache-control": "no-store"},
        ),
        PREFIX,
    )
    assert unexpected is not None and unexpected["kind"] == "unexpected_preview"
    with pytest.raises(proof_script.shared.ProofFailure, match="unexpected_preview_response_path"):
        proof_script._assert_preview_responses([descriptor, bytes_response, unexpected])

    bad_bytes = dict(bytes_response)
    bad_bytes["content_type"] = "video/webm"
    with pytest.raises(
        proof_script.shared.ProofFailure, match="preview_bytes_content_type_invalid"
    ):
        proof_script._assert_preview_responses([descriptor, bad_bytes])


def test_video_wait_predicates_are_scoped_to_the_selected_locator(proof_script):
    assert all(
        "document.querySelector" not in predicate
        for predicate in (
            proof_script._VIDEO_METADATA_READY,
            proof_script._VIDEO_PLAYED,
            proof_script._VIDEO_SEEKED,
        )
    )
