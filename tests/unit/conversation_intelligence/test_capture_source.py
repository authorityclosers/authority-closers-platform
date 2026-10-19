"""How a saved call was captured (ADR 0056 F2): one known header value; the migration matches."""

import re
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.capture_source import capture_source_header
from ac_platform.conversation_intelligence.guest_models import CAPTURE_SOURCES

MIGRATION = (
    Path(__file__).resolve().parents[3] / "db/migrations/versions/20261019_0100_capture_source.py"
)


def test_the_android_apps_three_ways_are_known() -> None:
    for source in ("android_dialer_pickup", "android_in_app_recorder", "android_call_recorder"):
        assert source in CAPTURE_SOURCES
        assert len(source) <= 32  # the column is VARCHAR(32)


def test_the_header_is_optional_but_must_be_one_known_source() -> None:
    assert capture_source_header([]) is None
    assert capture_source_header(["android_call_recorder"]) == "android_call_recorder"
    for bad in (["file_name_guess"], ["android_call_recorder", "android_call_recorder"], [""]):
        with pytest.raises(ConversationError) as refused:
            capture_source_header(bad)
        assert refused.value.status == 422


def test_the_migration_allows_exactly_the_models_sources() -> None:
    text = MIGRATION.read_text()
    upgrade = text[text.index("def upgrade") : text.index("def downgrade")]
    assert tuple(re.findall(r"'([a-z_]+)'", upgrade)) == CAPTURE_SOURCES
    downgrade = text[text.index("def downgrade") :]
    old = re.findall(r"\('([a-z_]+)'::character varying\)", downgrade)
    assert tuple(old) == CAPTURE_SOURCES[:-2]
    assert "requires forward recovery" in downgrade
