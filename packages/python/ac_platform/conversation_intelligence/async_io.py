"""Join owned filesystem work before cancellation can release authority fences."""

import asyncio
from collections.abc import Callable


async def join_thread[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    operation = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        # Task.cancel() cannot stop a worker thread. Repeated cancellation must
        # not let a surrounding DB transaction or private-directory guard exit.
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not operation.cancelled():
            operation.exception()
        raise
