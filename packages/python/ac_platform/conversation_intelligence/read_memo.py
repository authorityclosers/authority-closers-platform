"""Reuse verified reads within one read-only request transaction.

A GET handler opts in with ``memoized_reads(database)``. While that same root
transaction is open (and outside any savepoint), a check or lookup that already
succeeded is answered again from the memo instead of the database:

* account admission: the person, session, tenant and membership rows are locked
  by the first admission; session expiry is re-checked against the clock;
* tenant admission: the tenant row is share-locked;
* organisation read authority, when the membership row exists (share-locked);
* a submission's owner scope, recorded only once this transaction holds the
  recording's share lock; account admission and the permission's retention
  deadline are re-checked against the clock on every reuse;
* with that recording lock held: the recording, its latest report draft,
  retained version and completed run, the outcome of verifying the draft's
  stored evidence, saved checkpoints and the C2 segment texts used by
  withholding (sensitive marks themselves are always read fresh).

Each of these inputs is locked by this transaction, append-only in the database,
or changed only by writers that first take the recording lock for update
(deletion, erasure, new drafts and checkpoints), so a repeated read would return
the same answer. A retained C5 version may be appended by an operator who holds
only a share lock; the request then serves the state it first read, as if that
commit had landed after the request. Failed checks are never memoised: they run
again exactly as before. Writes never opt in, and a memo whose transaction ended
(commit, rollback, deadlock retry) is never read.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

_KEY = "ac.read_memo"


class ReadMemo:
    """Values keyed by an exact read; bound to one root transaction."""

    __slots__ = ("transaction", "values")

    def __init__(self, transaction: object) -> None:
        self.transaction = transaction
        self.values: dict[tuple[Any, ...], Any] = {}


def _root_transaction(database: Any) -> object | None:
    get_transaction = getattr(database, "get_transaction", None)
    if not callable(get_transaction):
        return None
    transaction = get_transaction()
    return None if transaction is None else getattr(transaction, "sync_transaction", None)


@contextmanager
def memoized_reads(database: Any) -> Iterator[None]:
    """Opt one read-only request transaction in; a no-op without a real session."""
    info = getattr(database, "info", None)
    transaction = _root_transaction(database)
    if not isinstance(info, dict) or transaction is None or _KEY in info:
        # Test doubles, no open transaction, or an enclosing scope already active.
        yield
        return
    info[_KEY] = ReadMemo(transaction)
    try:
        yield
    finally:
        info.pop(_KEY, None)


def active_memo(database: Any) -> ReadMemo | None:
    """The memo of this database's current transaction, if the request opted in."""
    info = getattr(database, "info", None)
    memo = info.get(_KEY) if isinstance(info, dict) else None
    if not isinstance(memo, ReadMemo) or _root_transaction(database) is not memo.transaction:
        return None
    in_nested = getattr(database, "in_nested_transaction", None)
    if callable(in_nested) and in_nested():
        # A savepoint rollback would release locks taken inside it.
        return None
    return memo


def mark_recording_locked(database: Any, recording_id: UUID) -> None:
    """Record that this transaction holds the recording's share lock."""
    memo = active_memo(database)
    if memo is not None:
        memo.values[("locked_recording", recording_id)] = True


def fenced_memo(database: Any, recording_id: UUID) -> ReadMemo | None:
    """The active memo, only while this transaction holds the recording's lock."""
    memo = active_memo(database)
    if memo is None or ("locked_recording", recording_id) not in memo.values:
        return None
    return memo


def owner_scope_key(
    ownership: object,
    submission_id: object,
    *,
    token: str | None,
    actor: object,
    shared_identity_locks: bool,
    allow_organisation_read: bool,
    allow_organisation_start: bool = False,
) -> tuple[Any, ...]:
    """Every argument of an owner check; a cached scope answers only the same check."""
    return (
        "owner_scope",
        ownership,
        submission_id,
        token,
        actor,
        shared_identity_locks,
        allow_organisation_read,
        allow_organisation_start,
    )
