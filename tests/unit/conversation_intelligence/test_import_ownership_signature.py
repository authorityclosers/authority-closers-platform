"""Regression (16 Oct, dev 500 on every import upload): the import grant's
ownership override accepts every keyword its base passes, and never widens."""

import inspect

from ac_platform.conversation_intelligence.bulk_import_ownership import ImportOwnership
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership


def test_import_override_accepts_every_base_keyword() -> None:
    base = inspect.signature(GuestOwnership._owned_usage).parameters
    override = inspect.signature(ImportOwnership._owned_usage).parameters
    missing = [name for name in base if name not in override]
    assert missing == []


def test_import_override_never_forwards_organisation_paths() -> None:
    source = inspect.getsource(ImportOwnership._owned_usage)
    assert "del allow_organisation_read, allow_organisation_start" in source
    assert "allow_organisation_start=" not in source.split("super()._owned_usage(")[1]
