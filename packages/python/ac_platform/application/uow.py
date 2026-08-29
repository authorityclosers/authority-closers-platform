from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from ac_platform.kernel.events import EventEnvelope


class UnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def add_event(self, event: EventEnvelope) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
