"""One explicit decision for an exact selection; no source or member authority inferred."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.bulk_import_contracts import ImportConfirmation
from ac_platform.conversation_intelligence.bulk_import_preview import BatchManifest
from ac_platform.conversation_intelligence.checkpoints import content_hash


def confirmation():
    manifest = BatchManifest.model_validate(
        {
            "files": [
                {"relative_path": "स्वामिनी/one", "source_sha256": "a" * 64, "source_bytes": 3},
                {"relative_path": "Unknown/two.wav", "source_sha256": "b" * 64, "source_bytes": 7},
            ]
        }
    )
    return {
        "manifest": manifest.model_dump(mode="json"),
        "manifest_sha256": content_hash(manifest.model_dump(mode="json")),
        "policy_sha256": "c" * 64,
        "folders": [
            {"folder": "स्वामिनी", "person_id": str(uuid4())},
            {"folder": "Unknown", "person_id": None},
        ],
        "rights_confirmed": True,
    }


def test_confirmed_selection_retains_the_explicit_member_and_unassigned_decision():
    value = confirmation()
    result = ImportConfirmation.model_validate(value)
    assert result.folders[0].person_id == value["folders"][0]["person_id"]
    assert result.folders[1].person_id is None


@pytest.mark.parametrize("action", [None, False, 1, "true", "accepted"])
def test_a_batch_never_defaults_or_coerces_the_uploaders_consent(action):
    value = confirmation()
    value["rights_confirmed"] = action
    with pytest.raises(ValidationError):
        ImportConfirmation.model_validate(value)


def test_consent_is_required_not_defaulted_from_a_preview_or_policy_hash():
    value = confirmation()
    del value["rights_confirmed"]
    with pytest.raises(ValidationError):
        ImportConfirmation.model_validate(value)


@pytest.mark.parametrize("field", ["relative_path", "source_sha256", "source_bytes"])
def test_source_selection_cannot_change_after_the_displayed_preview(field):
    value = confirmation()
    value["manifest"]["files"][0][field] = {
        "relative_path": "स्वामिनी/other",
        "source_sha256": "d" * 64,
        "source_bytes": 4,
    }[field]
    with pytest.raises(ValidationError, match="selected files changed"):
        ImportConfirmation.model_validate(value)


def test_every_folder_needs_one_explicit_choice():
    for kind in ("missing", "duplicate", "unrelated"):
        value = confirmation()
        if kind == "missing":
            value["folders"].pop()
        elif kind == "duplicate":
            value["folders"].append(value["folders"][0])
        else:
            value["folders"][1]["folder"] = "Unrelated"
        with pytest.raises(ValidationError, match="each folder exactly once"):
            ImportConfirmation.model_validate(value)


@pytest.mark.parametrize("member", ["fake", "00000000-0000-0000-0000-000000000000", True])
def test_a_name_or_invalid_identity_does_not_become_a_member_id(member):
    value = confirmation()
    value["folders"][0]["person_id"] = member
    with pytest.raises(ValidationError):
        ImportConfirmation.model_validate(value)


def test_identical_bytes_cannot_silently_choose_between_different_members():
    value = confirmation()
    value["folders"][1]["person_id"] = str(uuid4())
    value["manifest"]["files"][1]["source_sha256"] = "a" * 64
    value["manifest_sha256"] = content_hash(value["manifest"])
    with pytest.raises(ValidationError, match="different members"):
        ImportConfirmation.model_validate(value)
    value["folders"][1]["person_id"] = value["folders"][0]["person_id"]
    ImportConfirmation.model_validate(value)
