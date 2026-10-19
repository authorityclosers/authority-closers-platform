"""Sign in for a bounded time, so no request can hold a pooled connection for minutes.

On 19 Oct a review audio stream kept the locking sign-in (Person and Session
FOR UPDATE) and its connection for as long as a phone held the stream open.
Every other request of that person queued behind it, each holding a pooled
connection, until the production pool ran dry. Routes that stream, or that
everyone polls, sign in here: inside a time budget, with short lock and
statement timeouts, and they finish their transaction before the bytes flow.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ac_platform.http.auth import AuthenticatedTransaction, RequireActor

BUSY = "Sales Xray is busy for a moment. Try again."
# No statement in a bounded sign-in waits longer than this for a row lock.
LOCK_TIMEOUT_MS = 2000
# lock_not_available, query_canceled (statement_timeout)
_GAVE_UP = {"55P03", "57014"}


def busy() -> HTTPException:
    return HTTPException(
        503,
        BUSY,
        headers={"Cache-Control": "private, no-store", "Vary": "Cookie", "Retry-After": "30"},
    )


def read_only(require_actor: RequireActor) -> RequireActor:
    """The read-only sign-in (shared locks, no session write) when the app has one."""
    resolver: RequireActor = getattr(require_actor, "read_only", require_actor)
    return resolver


@asynccontextmanager
async def signed_in(
    resolver: RequireActor, request: Request, budget: float
) -> AsyncIterator[AuthenticatedTransaction]:
    """Sign in and work within ``budget`` seconds, or answer 503 and free the connection.

    A cancelled lock wait ends on the server too, so a slow neighbour can delay a
    request by seconds, never hold a pooled connection for minutes. The
    transaction ends with the block: return a streaming response from inside it
    and the stream itself holds no locks and no connection.
    """
    try:
        async with asyncio.timeout(budget):
            async with asynccontextmanager(resolver)(request) as auth:
                await auth.database.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'"))
                await auth.database.execute(
                    text(f"SET LOCAL statement_timeout = '{int(budget * 1000)}ms'")
                )
                yield auth
    except TimeoutError:
        raise busy() from None
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in _GAVE_UP:
            raise busy() from None
        raise
