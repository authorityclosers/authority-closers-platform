"""Read-only browser over the AC Sandbox's imported full calls (AUT-1798).

Where the synthetic-v1 folder isn't mounted, the same fictional calls can be
read from what the sandbox import stored (``conversation_synthetic_records``,
``kind='call'``, sandbox organisations only). Answers have the folder
browser's shape and labels: metadata as the row, transcript lines, and the
answer key without ``fixture_truth``. A rep's private authored coaching is
never read. Nothing here writes.

Each full call is about 100 KB of JSON, so filtering in SQL per request would
parse every bundle. The row index (metadata only) is built once per import
state and kept in memory; a cheap count/last-import check invalidates it. One
call is read by its primary key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.synthetic_dataset import (
    _CALL_ID,
    call_view,
    index_page,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)

Record = ConversationSyntheticRecord
_Signature = tuple[int, datetime | None]
# Keyed by the sandbox tenants read; at most a few distinct sets ever exist.
_INDEX_CACHE: dict[tuple[UUID, ...], tuple[_Signature, list[dict[str, Any]]]] = {}
_CACHE_LIMIT = 4


def _text(value: Any, limit: int = 160) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def metadata_row(key: str, metadata: Any) -> dict[str, Any]:
    """The folder browser's row, from a sandbox call's authored metadata."""
    meta = metadata if isinstance(metadata, dict) else {}
    return {
        "call_id": key,
        "business_id": _text(meta.get("business_id")),
        "journey_id": _text(meta.get("journey_id")),
        "rep_id": _text(meta.get("rep_id")),
        "at": _text(meta.get("at"), 40),
        "sequence": _number(meta.get("sequence")),
        "language_mix": _text(meta.get("language_mix"), 32),
        "scenario": _text(meta.get("scenario")),
        "outcome": _text(meta.get("outcome")),
        "crm_stage": _text(meta.get("crm_stage")),
        "deal_value_inr": _number(meta.get("net_deal_value_inr", meta.get("deal_value_inr"))),
        "duration_ms": _number(meta.get("duration_ms")),
        "audio_status": _text(meta.get("audio_status")),
    }


class SandboxCallBrowser:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def _tenants(self) -> tuple[UUID, ...]:
        rows = await self.database.scalars(
            select(ConversationSandboxOrganisation.tenant_id).order_by(
                ConversationSandboxOrganisation.tenant_id
            )
        )
        return tuple(rows.all())

    async def _rows(self, tenants: tuple[UUID, ...]) -> list[dict[str, Any]]:
        if not tenants:
            return []
        scope = (Record.tenant_id.in_(tenants), Record.kind == "call")
        count, last = (
            await self.database.execute(
                select(func.count(), func.max(Record.imported_at)).where(*scope)
            )
        ).one()
        signature: _Signature = (int(count), last)
        cached = _INDEX_CACHE.get(tenants)
        if cached is not None and cached[0] == signature:
            return cached[1]
        newest: dict[str, tuple[int, dict[str, Any]]] = {}
        result = await self.database.execute(
            select(Record.synthetic_key, Record.revision, Record.payload["metadata"]).where(*scope)
        )
        for key, revision, metadata in result.all():
            if _CALL_ID.fullmatch(key) and (key not in newest or revision > newest[key][0]):
                newest[key] = (revision, metadata_row(key, metadata))
        rows = [row for _, row in newest.values()]
        if len(_INDEX_CACHE) >= _CACHE_LIMIT:
            _INDEX_CACHE.clear()
        _INDEX_CACHE[tenants] = (signature, rows)
        return rows

    async def index(
        self,
        *,
        business: str | None = None,
        language: str | None = None,
        outcome: str | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        page = index_page(
            await self._rows(await self._tenants()),
            business=business,
            language=language,
            outcome=outcome,
            query=query,
            offset=offset,
            limit=limit,
        )
        return {**page, "source": "sandbox"}

    async def call(self, call_id: str) -> dict[str, Any]:
        tenants = await self._tenants()
        if not _CALL_ID.fullmatch(call_id) or not tenants:
            raise ConversationNotFound("Synthetic call not found.")
        row = await self.database.scalar(
            select(Record)
            .where(
                Record.tenant_id.in_(tenants),
                Record.kind == "call",
                Record.synthetic_key == call_id,
            )
            .order_by(Record.revision.desc(), Record.tenant_id)
            .limit(1)
        )
        if row is None or not isinstance(row.payload, dict):
            raise ConversationNotFound("Synthetic call not found.")
        payload = row.payload
        view = call_view(
            metadata_row(call_id, payload.get("metadata")),
            payload.get("transcript"),
            payload.get("answer_key"),
        )
        return {**view, "source": "sandbox"}
