"""Read-only batch manifest preview under the current organisation administrator.

Paths and hashes are browser inventory hints, never storage paths, duration
receipts or imported-source proof. A proposed member is not an ownership grant.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership

MAX_BATCH_FILES = 256
MAX_BATCH_BYTES = 1024 * 1024 * 1024


class BatchSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    relative_path: str = Field(min_length=1, max_length=512)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bytes: int = Field(ge=1, le=MAX_AUDIO_BYTES)

    @field_validator("relative_path")
    @classmethod
    def bounded_relative_path(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value)
        parts = value.split("/")
        if (
            len(value) > 512
            or value.startswith("/")
            or "\\" in value
            or (len(value) > 1 and value[0].isascii() and value[0].isalpha() and value[1] == ":")
            or any(
                ord(character) < 32 or ord(character) == 127 or 0xD800 <= ord(character) <= 0xDFFF
                for character in value
            )
            or any(unicodedata.normalize("NFKC", part) in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("Choose paths relative to the selected folder without traversal.")
        return value

    @property
    def folder(self) -> str:
        return self.relative_path.split("/", 1)[0] if "/" in self.relative_path else ""


class BatchManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    files: list[BatchSource] = Field(min_length=1, max_length=MAX_BATCH_FILES)

    @model_validator(mode="after")
    def bounded_inventory(self) -> Self:
        if sum(source.source_bytes for source in self.files) > MAX_BATCH_BYTES:
            raise ValueError("Choose a batch up to 1 GiB; larger folders can use separate batches.")
        if len({source.relative_path for source in self.files}) != len(self.files):
            raise ValueError("Each relative file path must occur once in the batch.")
        return self


@dataclass(frozen=True)
class ImportMember:
    person_id: UUID
    display_name: str | None
    first_name: str | None


def _name(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def project_import_preview(
    manifest: BatchManifest, members: Sequence[ImportMember]
) -> dict[str, Any]:
    """Suggest only an unambiguous exact name; the uploader must confirm IDs later."""

    full: dict[str, set[UUID]] = defaultdict(set)
    first: dict[str, set[UUID]] = defaultdict(set)
    for member in members:
        if _name(member.display_name):
            full[_name(member.display_name)].add(member.person_id)
        if _name(member.first_name):
            first[_name(member.first_name)].add(member.person_id)
    folder_files: dict[str, list[BatchSource]] = defaultdict(list)
    first_path: dict[str, str] = {}
    files = []
    for source in manifest.files:
        folder_files[source.folder].append(source)
        files.append(
            {
                **source.model_dump(),
                "folder": source.folder,
                "duplicate_of_path": first_path.get(source.source_sha256),
            }
        )
        first_path.setdefault(source.source_sha256, source.relative_path)
    folders = []
    for folder, sources in folder_files.items():
        candidates = full.get(_name(folder)) or first.get(_name(folder)) or set()
        folders.append(
            {
                "folder": folder,
                "proposed_person_id": str(next(iter(candidates))) if len(candidates) == 1 else None,
                "match_state": (
                    "suggested"
                    if len(candidates) == 1
                    else "ambiguous"
                    if candidates
                    else "unassigned"
                ),
                "file_count": len(sources),
                "source_bytes": sum(source.source_bytes for source in sources),
            }
        )
    return {
        "manifest_sha256": content_hash(manifest.model_dump(mode="json")),
        "requires_confirmation": True,
        "total_files": len(manifest.files),
        "total_bytes": sum(source.source_bytes for source in manifest.files),
        "unique_source_hints": len(first_path),
        "files": files,
        "folders": folders,
        "members": [
            {
                "person_id": str(member.person_id),
                "display_name": member.display_name or member.first_name or "Member",
            }
            for member in members
        ],
    }


async def preview_import(
    ownership: GuestOwnership, actor: ActorContext | None, manifest: BatchManifest
) -> dict[str, Any]:
    if actor is None or actor.tenant_id != ownership.tenant_id:
        raise ConversationDenied("Select an organisation where you are an owner or admin.")
    await ConversationApplication(ownership.database, clock=ownership.clock).admit(
        actor, shared_identity_locks=True
    )
    if not await ownership.organisation_call_reader(actor):
        raise ConversationDenied("Select an organisation where you are an owner or admin.")
    rows = (
        await ownership.database.execute(
            select(Person.id, Person.display_name, Person.first_name)
            .join(Membership, Membership.person_id == Person.id)
            .where(
                Membership.tenant_id == ownership.tenant_id,
                Membership.role.in_(("owner", "admin", "member")),
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Person.status == "active",
            )
            .order_by(Person.display_name, Person.first_name, Person.id)
        )
    ).all()
    result = project_import_preview(manifest, [ImportMember(*row) for row in rows])
    return {"tenant_id": str(ownership.tenant_id), **result}
