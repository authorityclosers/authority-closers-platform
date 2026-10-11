"""Explicit batch confirmation; a preview hint never becomes an ownership grant."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ac_platform.conversation_intelligence.bulk_import_preview import BatchManifest
from ac_platform.conversation_intelligence.checkpoints import content_hash

IMPORT_ATTESTATION = "I confirm we have the right to analyse these recordings"
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class FolderConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    folder: str = Field(max_length=512)
    person_id: str | None = Field(pattern=_UUID_PATTERN)

    @field_validator("person_id")
    @classmethod
    def nonzero_member(cls, value: str | None) -> str | None:
        if value is not None and UUID(value).int == 0:
            raise ValueError("Confirm a current member ID or leave the folder unassigned.")
        return value


class ImportConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    manifest: BatchManifest
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    folders: list[FolderConfirmation] = Field(min_length=1, max_length=256)
    rights_confirmed: Literal[True]

    @field_validator("rights_confirmed", mode="before")
    @classmethod
    def affirmative_action(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Confirm the recording rights for this exact batch.")
        return value

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if self.manifest_sha256 != content_hash(self.manifest.model_dump(mode="json")):
            raise ValueError("The selected files changed. Review the folder again.")
        expected = {source.folder for source in self.manifest.files}
        actual = [folder.folder for folder in self.folders]
        if len(set(actual)) != len(actual) or set(actual) != expected:
            raise ValueError("Confirm each folder exactly once, including unassigned folders.")
        owners = {folder.folder: folder.person_id for folder in self.folders}
        source_owners: dict[str, str] = {}
        for source in self.manifest.files:
            owner = owners[source.folder]
            if owner is None:
                continue
            previous = source_owners.setdefault(source.source_sha256, owner)
            if previous != owner:
                raise ValueError(
                    "The same recording is assigned to different members. Choose one owner."
                )
        return self
