from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.media.api_contracts import (
    UploadCompleteRequest,
    UploadIntentRequest,
)
from ac_platform.media.models import MediaPurpose

CHECKSUM = "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a"
ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_profile_avatar_checksum_intent_and_completion_are_server_schema_compatible() -> None:
    intent = UploadIntentRequest.model_validate(
        {
            "purpose": MediaPurpose.AVATAR,
            "filename": "headshot.jpg",
            "content_type": "image/jpeg; charset=binary",
            "content_length": 4,
            "checksum_sha256": CHECKSUM.upper(),
            "asset_id": ASSET_ID,
            "supersedes_version_id": VERSION_ID,
            "crop": {
                "x": 0.21875,
                "y": 0,
                "width": 0.5625,
                "height": 1,
                "rotation_degrees": 0,
            },
        }
    )
    assert intent.checksum_sha256 == CHECKSUM
    assert intent.content_type == "image/jpeg"

    completion = UploadCompleteRequest.model_validate(
        {"actual_bytes": 4, "checksum_sha256": CHECKSUM}
    )
    assert completion.checksum_sha256 == CHECKSUM

    with pytest.raises(ValidationError):
        UploadIntentRequest.model_validate(
            {
                "purpose": MediaPurpose.AVATAR,
                "filename": "headshot.jpg",
                "content_type": "image/jpeg",
                "content_length": 4,
                "checksum_sha256": CHECKSUM,
                "unexpected_client_field": "must be rejected",
            }
        )
