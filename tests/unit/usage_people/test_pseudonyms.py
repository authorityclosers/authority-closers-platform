"""Pseudonymous person ids: the export's two-pass hash is HMAC-SHA-256, keyed per environment."""

from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

import pytest

from ac_platform.usage_people.pseudonyms import PATTERN, pads, pseudonym

PERSON = UUID("6a1b2c3d-4e5f-4061-8a7b-9c0d1e2f3a4b")


def test_the_pseudonym_is_hmac_sha256_of_the_person_id() -> None:
    key = bytes(range(32))
    inner, outer = pads(key)
    expected = hmac.new(key, str(PERSON).encode(), hashlib.sha256).hexdigest()[:16]
    assert pseudonym(inner, outer, PERSON) == "p_" + expected
    assert pseudonym(inner, outer, str(PERSON)) == pseudonym(inner, outer, PERSON)
    assert PATTERN.fullmatch(pseudonym(inner, outer, PERSON))
    # Another environment's key gives another pseudonym for the same person.
    other = pads(bytes(range(1, 33)))
    assert pseudonym(*other, PERSON) != pseudonym(inner, outer, PERSON)


def test_pads_need_a_real_key() -> None:
    with pytest.raises(ValueError):
        pads(b"short")
    with pytest.raises(ValueError):
        pads(b"x" * 65)
    assert [len(pad) for pad in pads(b"k" * 32)] == [64, 64]
