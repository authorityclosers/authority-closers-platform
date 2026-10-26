"""The worker's provider call re-checks its scope without holding people's rows (demo P1,
26 Oct 2026: accepting a report froze that person's requests for the call, ~28 s).

``inference_worker._dispatch`` re-checks the call's scope in the transaction it keeps open
across the provider call (up to 860 s). Inside ``provider_call()`` the reads that would
otherwise lock a person's identity, the provider configuration's controller, or the budget and
minute accounts are plain reads: the reservation is already committed, and the next
transaction re-admits with the canonical locks. Everywhere else nothing changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_IN_CALL: ContextVar[bool] = ContextVar("xray_provider_call", default=False)


@contextmanager
def provider_call() -> Iterator[None]:
    """Worker only: around the re-check in the transaction that spans the provider call."""
    token = _IN_CALL.set(True)
    try:
        yield
    finally:
        _IN_CALL.reset(token)


def in_provider_call() -> bool:
    return _IN_CALL.get()
