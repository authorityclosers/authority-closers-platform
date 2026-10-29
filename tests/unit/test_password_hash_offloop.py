"""CPU-heavy credential work stays off-loop, with a bounded memory multiplier."""

import asyncio
import threading
import time
from unittest.mock import AsyncMock

import pytest

from ac_platform.identity import password_auth as auth


async def test_scrypt_wrappers_run_off_loop_and_limit_concurrency(monkeypatch):
    main = threading.get_ident()
    active = maximum = 0
    lock = threading.Lock()

    def hash_value(value):
        nonlocal active, maximum
        assert threading.get_ident() != main
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return value

    monkeypatch.setattr(auth, "hash_password", hash_value)
    assert await asyncio.gather(*(auth._hash_password(str(i)) for i in range(6))) == [
        str(i) for i in range(6)
    ]
    assert 1 <= maximum <= 2

    def verify(value, encoded):
        assert threading.get_ident() != main
        return value == encoded

    monkeypatch.setattr(auth, "verify_password", verify)
    assert await auth._verify_password("equal", "equal")
    assert not await auth._verify_password("different", "equal")


async def test_unknown_account_still_verifies_dummy_off_loop(monkeypatch):
    database = AsyncMock()
    database.execute.return_value.one_or_none = lambda: None
    main = threading.get_ident()
    seen = []

    def verify(value, encoded):
        assert threading.get_ident() != main
        seen.append(encoded)
        return False

    monkeypatch.setattr(auth, "verify_password", verify)
    with pytest.raises(auth.InvalidPasswordCredentials):
        await auth.PasswordIdentityService(
            database, token_secret=b"test-only-token-context"
        ).authenticate(
            email="unknown@example.test",
            password="a valid test passphrase",  # noqa: S106 - test input
        )
    assert seen == [auth._DUMMY_PASSWORD_HASH]
