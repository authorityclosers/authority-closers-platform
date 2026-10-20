"""Providers hub, slice 2: provider keys' free checks read safely and say plainly what they
found (owner, 20 Oct 2026). Pure: no network, no database."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from ac_platform.provider_hub.catalogue import BY_ID
from ac_platform.provider_hub.keys import FREE_READS, FreeRead, model_ids, outcome_words
from ac_platform.provider_hub.models import hub_view, models_for

LIST = FreeRead("https://example.invalid/v1/models", "Authorization", "Bearer ")


def test_every_free_check_is_a_fixed_https_address_of_a_catalogue_provider() -> None:
    for provider, check in FREE_READS.items():
        assert provider in BY_ID
        parts = urlsplit(check.url)
        assert parts.scheme == "https" and parts.hostname and not parts.username
        assert check.header in {"Authorization", "x-goog-api-key", "x-api-key", "xi-api-key"}
    # Speech providers whose only reads list customer jobs get no check at all.
    for provider in ("assemblyai", "gladia", "speechmatics", "sarvam", "custom"):
        assert provider not in FREE_READS


def test_model_ids_come_from_each_answer_shape_and_nothing_else() -> None:
    openai_style = {"data": [{"id": "gpt-x"}, {"id": "gpt-x"}, {"id": "bad id"}, "x", {}]}
    assert model_ids(LIST, openai_style) == ["gpt-x"]
    gemini = FREE_READS["gemini"]
    assert model_ids(gemini, {"models": [{"name": "models/gemini-3.8-flash"}]}) == [
        "gemini-3.8-flash"
    ]
    elevenlabs = FREE_READS["elevenlabs"]
    assert model_ids(elevenlabs, [{"model_id": "scribe_v1"}, {"model_id": "eleven_v3"}]) == [
        "scribe_v1",
        "eleven_v3",
    ]
    assert model_ids(FREE_READS["openrouter"], {"data": {"usage": 1}}) == []
    assert model_ids(LIST, None) == [] and model_ids(LIST, {"data": "nope"}) == []
    many = {"data": [{"id": f"m-{n}"} for n in range(1500)]}
    assert len(model_ids(LIST, many)) == 1000


@pytest.mark.parametrize(
    ("status", "models", "listing", "ok", "words", "fix"),
    [
        (200, 42, True, True, "The key works: 42 models listed.", None),
        (200, 1, True, True, "The key works: 1 model listed.", None),
        (200, 0, False, True, "The key works.", None),
        (0, 0, True, False, "could not be reached", "wait"),
        (401, 0, True, False, "The key was refused", "key"),
        (402, 0, True, False, "Out of credit", "console"),
        (404, 0, True, False, "check address answered 404", "engineer"),
        (503, 0, True, False, "trouble on its side", "wait"),
    ],
)
def test_a_check_says_plainly_whether_the_key_works(
    status: int, models: int, listing: bool, ok: bool, words: str, fix: str | None
) -> None:
    said_ok, said, said_fix = outcome_words(status, models, listing)
    assert (said_ok, said_fix) == (ok, fix)
    assert words in said


def test_a_tested_keys_models_join_the_hub_without_repeating_known_ones() -> None:
    groq = BY_ID["groq"]
    listed = {"groq": ["llama-4-70b", "llama-4-70b-again"], "openai": ["gpt-x"]}
    rows = models_for(groq, [], listed)
    assert [row["id"] for row in rows if row["source"] == "provider"] == [
        "llama-4-70b",
        "llama-4-70b-again",
    ]
    assert models_for(groq, []) == [row for row in rows if row["source"] != "provider"]
    view = hub_view([], fetched_at=None, problem=None, selected="groq", listed=listed)
    groq_row = next(row for row in view["providers"] if row["id"] == "groq")
    assert groq_row["models"] >= 2
    assert {row["id"] for row in view["models"]} >= {"llama-4-70b", "llama-4-70b-again"}
