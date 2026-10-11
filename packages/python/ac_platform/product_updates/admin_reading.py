"""Read-only Admin list of product notes (AUT-1798): the newest version of each.

What Sales Xray users are shown as "What's new", with its status (draft,
approved, published), audience and release. Nothing is approved, published
or edited from here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.product_updates.models import ProductUpdate

MAX_NOTES = 200


async def latest_notes(database: AsyncSession) -> dict[str, Any]:
    rows = (
        await database.scalars(
            select(ProductUpdate)
            .order_by(
                ProductUpdate.note_date.desc(), ProductUpdate.note_key, ProductUpdate.version.desc()
            )
            .limit(MAX_NOTES * 4)
        )
    ).all()
    newest: dict[str, ProductUpdate] = {}
    for row in rows:
        current = newest.get(row.note_key)
        if current is None or row.version > current.version:
            newest[row.note_key] = row
    notes = sorted(newest.values(), key=lambda row: (row.note_date, row.note_key), reverse=True)[
        :MAX_NOTES
    ]
    return {
        "notes": [
            {
                "key": row.note_key,
                "version": row.version,
                "title": row.title,
                "items": list(row.items or []),
                "date": row.note_date.isoformat(),
                "audience": row.audience,
                "status": row.status,
                "major": bool(row.major),
                "release_id": row.release_id,
                "source_pr": row.source_pr,
                "created_by": row.created_by,
                "published_at": None if row.published_at is None else row.published_at.isoformat(),
            }
            for row in notes
        ]
    }
