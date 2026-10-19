"""19 Oct incident: a review request may wait seconds, never hold a connection for minutes."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from ac_platform.http.sales_xray_review import LOCK_TIMEOUT_MS, signed_in


class _Database:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


def _resolver(database: _Database, *, wait: float = 0.0, log: list[str] | None = None):
    async def resolve(request: object):
        if wait:
            await asyncio.sleep(wait)  # a sign-in stuck behind someone else's row lock
        try:
            yield SimpleNamespace(database=database)
        except BaseException:
            (log if log is not None else []).append("rolled back")
            raise
        (log if log is not None else []).append("committed")

    return resolve


def test_a_stuck_sign_in_answers_busy_within_the_budget() -> None:
    async def run() -> None:
        started = time.monotonic()
        with pytest.raises(HTTPException) as caught:
            async with signed_in(_resolver(_Database(), wait=60), object(), 0.2):
                raise AssertionError("never signed in")
        assert caught.value.status_code == 503
        assert caught.value.headers["Retry-After"] == "30"
        assert time.monotonic() - started < 2

    asyncio.run(run())


def test_every_review_transaction_caps_lock_waits_and_statements() -> None:
    async def run() -> None:
        database = _Database()
        log: list[str] = []
        async with signed_in(_resolver(database, log=log), object(), 5) as auth:
            assert auth.database is database
        assert database.statements == [
            f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'",
            "SET LOCAL statement_timeout = '5000ms'",
        ]
        assert log == ["committed"]

    asyncio.run(run())


@pytest.mark.parametrize("sqlstate, busy", [("55P03", True), ("57014", True), ("23505", False)])
def test_a_lock_or_statement_timeout_is_busy_and_other_errors_are_not(
    sqlstate: str, busy: bool
) -> None:
    error = DBAPIError("SELECT 1", {}, SimpleNamespace(sqlstate=sqlstate))

    async def run() -> None:
        log: list[str] = []
        with pytest.raises(HTTPException if busy else DBAPIError) as caught:
            async with signed_in(_resolver(_Database(), log=log), object(), 5):
                raise error
        if busy:
            assert caught.value.status_code == 503
        assert log == ["rolled back"]

    asyncio.run(run())


def test_a_slow_read_after_sign_in_is_cut_off_too() -> None:
    async def run() -> None:
        log: list[str] = []
        with pytest.raises(HTTPException):
            async with signed_in(_resolver(_Database(), log=log), object(), 0.2):
                await asyncio.sleep(60)
        assert log == ["rolled back"]

    asyncio.run(run())
