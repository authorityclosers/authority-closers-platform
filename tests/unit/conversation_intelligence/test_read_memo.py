"""Request-scoped read reuse is bound to one transaction and to the recording fence."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from ac_platform.conversation_intelligence.read_memo import (
    active_memo,
    fenced_memo,
    mark_recording_locked,
    memoized_reads,
    owner_scope_key,
)


class _Session:
    """The AsyncSession surface the memo uses: info, get_transaction, savepoints."""

    def __init__(self) -> None:
        self.info: dict[str, object] = {}
        self.root = SimpleNamespace(sync_transaction=object())
        self.nested = False

    def get_transaction(self) -> SimpleNamespace | None:
        return self.root

    def in_nested_transaction(self) -> bool:
        return self.nested


def test_memo_exists_only_inside_its_scope_and_root_transaction() -> None:
    database = _Session()
    assert active_memo(database) is None
    with memoized_reads(database):
        memo = active_memo(database)
        assert memo is not None
        # A savepoint could release locks on rollback: no reuse inside one.
        database.nested = True
        assert active_memo(database) is None
        database.nested = False
        # A new root transaction (commit, rollback or retry) never reads the old memo.
        database.root = SimpleNamespace(sync_transaction=object())
        assert active_memo(database) is None
    assert active_memo(database) is None and "ac.read_memo" not in database.info


def test_nested_scopes_share_one_memo_and_only_the_outer_scope_clears_it() -> None:
    database = _Session()
    with memoized_reads(database):
        outer = active_memo(database)
        with memoized_reads(database):
            assert active_memo(database) is outer
        assert active_memo(database) is outer
    assert active_memo(database) is None


def test_doubles_without_a_session_transaction_are_left_untouched() -> None:
    for database in (object(), SimpleNamespace(info={}), SimpleNamespace(get_transaction=None)):
        with memoized_reads(database):
            assert active_memo(database) is None


def test_recording_reads_reuse_only_after_this_transaction_locked_the_recording() -> None:
    database, recording, other = _Session(), uuid4(), uuid4()
    with memoized_reads(database):
        assert fenced_memo(database, recording) is None
        mark_recording_locked(database, recording)
        assert fenced_memo(database, recording) is active_memo(database)
        assert fenced_memo(database, other) is None
    mark_recording_locked(database, recording)  # no active memo: ignored
    assert fenced_memo(database, recording) is None


def test_owner_scope_key_distinguishes_every_authorisation_argument() -> None:
    ownership, submission, actor = object(), uuid4(), object()
    base = dict(token=None, actor=actor, shared_identity_locks=True, allow_organisation_read=False)
    keys = {
        owner_scope_key(ownership, submission, **base),
        owner_scope_key(ownership, submission, **{**base, "allow_organisation_read": True}),
        owner_scope_key(ownership, submission, **{**base, "shared_identity_locks": False}),
        owner_scope_key(ownership, submission, **base, allow_organisation_start=True),
        owner_scope_key(ownership, submission, **{**base, "actor": object()}),
        owner_scope_key(object(), submission, **base),
        owner_scope_key(ownership, uuid4(), **base),
    }
    assert len(keys) == 7
