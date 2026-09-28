"""Fictional reference histories exercise legacy, shared and fail-closed source resolution."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceObject as Source,
)
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceReference as Reference,
)
from ac_platform.conversation_intelligence.source_objects import resolve_source_key
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    SourceAudioKey,
    StorageError,
)


@pytest.mark.parametrize(
    "history",
    ["none", "live", "released", "deleted", "missing", "ref_tenant", "owner", "tenant", "hash"],
)
async def test_resolver_never_falls_back_from_invalid_reference(history: str) -> None:
    recording = ConversationRecording(
        id=uuid4(), tenant_id=uuid4(), person_id=uuid4(), source_sha256="a" * 64
    )
    source = Source(
        id=uuid4(), tenant_id=recording.tenant_id, source_sha256=recording.source_sha256
    )
    reference = Reference(
        recording_id=recording.id,
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        source_object_id=source.id,
    )
    if history == "released":
        reference.released_at = datetime.now(UTC)
    elif history == "deleted":
        source.deleted_at = datetime.now(UTC)
    elif history == "ref_tenant":
        reference.tenant_id = uuid4()
    elif history == "owner":
        reference.person_id = uuid4()
    elif history == "tenant":
        source.tenant_id = uuid4()
    elif history == "hash":
        source.source_sha256 = "b" * 64
    rows = {
        (Reference, recording.id): reference if history != "none" else None,
        (Source, source.id): source if history != "missing" else None,
    }
    db = AsyncMock(spec=AsyncSession)
    db.get.side_effect = lambda model, identifier: rows[model, identifier]
    if history == "none":
        assert await resolve_source_key(db, recording) == ObjectKey(
            recording.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO
        )
        db.get.assert_awaited_once_with(Reference, recording.id)
    elif history == "live":
        assert await resolve_source_key(db, recording) == SourceAudioKey(
            recording.tenant_id, recording.source_sha256
        )
    else:
        with pytest.raises(StorageError, match="^storage_object_missing$"):
            await resolve_source_key(db, recording)
