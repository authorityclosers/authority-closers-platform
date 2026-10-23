"""Round-robin memory that keeps one organisation's backlog from blocking the rest.

Claims were first-in-first-out across all organisations, so a bulk import of
hundreds of calls held every other organisation's analysis behind it. A worker
that claims per-organisation work keeps one ``TenantTurns`` and passes it to the
claim: the organisation served least recently goes first, and each
organisation's own queue keeps its order.

This is a scheduling preference only. It lives in the worker process (shared by
all of that worker's consumers), grants or blocks nothing, holds no customer
content and starts empty after a restart: every organisation then ties and the
queue order decides until each has been served once.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, case

# Organisations remembered per worker. Beyond this, the least recently served
# are forgotten, which ranks them with organisations never served: first.
MAX_TENANT_TURNS = 128


class TenantTurns:
    """Least-recently-served order of organisations, oldest first."""

    def __init__(self, capacity: int = MAX_TENANT_TURNS) -> None:
        if type(capacity) is not int or not 1 <= capacity <= MAX_TENANT_TURNS:
            raise ValueError(f"Tenant turn capacity must be 1 to {MAX_TENANT_TURNS}")
        self._capacity = capacity
        self._served: OrderedDict[UUID, None] = OrderedDict()

    def ranks(self) -> Mapping[UUID, int]:
        """Rank 1 is the least recently served; an organisation not listed ranks 0."""

        return {tenant_id: rank for rank, tenant_id in enumerate(self._served, start=1)}

    def served(self, tenant_id: UUID | None) -> None:
        """Move an organisation to the back of the line after one of its claims."""

        if tenant_id is None:
            return
        self._served.pop(tenant_id, None)
        self._served[tenant_id] = None
        while len(self._served) > self._capacity:
            self._served.popitem(last=False)


def turn_order(column: Any, ranks: Mapping[UUID, int] | None) -> ColumnElement[int] | None:
    """Sort key for ``column`` (an organisation id): its rank, 0 when not listed.

    Returns ``None`` when nothing has been served yet, so callers keep their
    plain queue order. Bounded like :class:`TenantTurns`; a caller-made mapping
    is checked here because it becomes SQL bind values.
    """

    if not ranks:
        return None
    if len(ranks) > MAX_TENANT_TURNS:
        raise ValueError(f"Tenant turns must list at most {MAX_TENANT_TURNS} organisations")
    if any(
        type(tenant_id) is not UUID or type(rank) is not int or rank < 1
        for tenant_id, rank in ranks.items()
    ):
        raise ValueError("Tenant turns must map organisation ids to positive ranks")
    return case(*((column == tenant_id, rank) for tenant_id, rank in ranks.items()), else_=0)


__all__ = ["MAX_TENANT_TURNS", "TenantTurns", "turn_order"]
