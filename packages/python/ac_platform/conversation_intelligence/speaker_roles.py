"""Strict names-free attribution snapshots; provenance grants no enforcement."""

from collections.abc import Mapping
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

RoleOrigin = Literal[
    "unverified_provider_labels",
    "text_predicted_roles",
    "model_named_roles",
    "user_confirmed_roles",
    "channel_mapped_roles",
]
SPEAKER_ROLE_ORIGINS = frozenset(get_args(RoleOrigin))


class _SpeakerRole(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    speaker_id: str = Field(min_length=1, max_length=256)
    role: Literal["seller", "prospect", "other"]
    is_account_holder: bool


class _SpeakerRolesSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    origin: RoleOrigin
    transcript_revision: str = Field(min_length=1, max_length=256)
    map_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    speakers: list[_SpeakerRole] = Field(max_length=32)

    @model_validator(mode="after")
    def role_shape(self) -> "_SpeakerRolesSnapshot":
        ids = [row.speaker_id for row in self.speakers]
        if len(set(ids)) != len(ids) or sum(row.is_account_holder for row in self.speakers) > 1:
            raise ValueError("speaker_roles_snapshot_invalid")
        if any(row.is_account_holder and row.role != "seller" for row in self.speakers):
            raise ValueError("speaker_roles_snapshot_invalid")
        return self


def validate_speaker_roles(
    snapshot: Mapping[str, Any], transcript: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a detached block bound to current C2; fail without source contents.

    Incomplete confirmed/channel attribution cannot retain an authoritative
    origin. Unresolved text/model attribution may contain only the known roles.
    """
    try:
        value = _SpeakerRolesSnapshot.model_validate(snapshot)
        known = {row["speaker_id"] for row in transcript["segments"]} - {"unattributed"}
        supplied = {row.speaker_id for row in value.speakers}
        if value.transcript_revision != transcript["revision"] or not supplied <= known:
            raise ValueError
        if value.origin in {"user_confirmed_roles", "channel_mapped_roles"} and (
            not supplied or supplied != known
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ValueError("speaker_roles_snapshot_invalid") from None
    return value.model_dump(mode="json")
