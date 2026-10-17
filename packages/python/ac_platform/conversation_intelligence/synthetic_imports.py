"""Sandbox-only admission: a current owner/admin of an explicitly flagged sandbox org.

The cookie HTTP import routes that used to live here were removed (cleanup
stage 1); the AC Sandbox is loaded by the direct-DB loaders under scripts/.
Coaching uses ``admit`` to decide whether fictional sandbox reads apply.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.bulk_imports import RecordingImports
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.kernel.authz import ActorContext


class SyntheticImports:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership = ownership
        self.database = ownership.database
        self.imports = RecordingImports(ownership)

    async def admit(self, actor: ActorContext) -> datetime:
        now = await self.imports.administrator(actor, shared_identity_locks=True)
        flag = await self.database.scalar(
            select(ConversationSandboxOrganisation)
            .where(ConversationSandboxOrganisation.tenant_id == actor.tenant_id)
            .with_for_update(read=True)
        )
        if flag is None:
            raise ConversationDenied(
                "Synthetic imports require an explicitly flagged sandbox organisation."
            )
        return now
