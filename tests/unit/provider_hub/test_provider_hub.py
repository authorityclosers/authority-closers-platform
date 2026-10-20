"""Admin's Providers hub (owner, 20 Oct 2026): search, models per provider, what the pipeline
can run, and OpenRouter's catalogue read safely. No network: the catalogue is a fixture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ac_platform.provider_hub.catalogue import BY_ID, PROVIDERS, find
from ac_platform.provider_hub.models import (
    REFRESH,
    OpenRouterCatalogue,
    hub_view,
    models_for,
    normalize_openrouter,
    pipeline_state,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

OPENROUTER: dict[str, Any] = {
    "data": [
        {
            "id": "google/gemini-3.8-flash",
            "name": "Google: Gemini 3.8 Flash",
            "context_length": 1_048_576,
            "architecture": {"input_modalities": ["text", "audio"], "output_modalities": ["text"]},
            "pricing": {"prompt": "0.00000075", "completion": "0.00000375"},
            "supported_parameters": ["response_format", "max_tokens"],
        },
        {
            "id": "openai/gpt-6-luna",
            "name": "OpenAI: GPT-6 Luna",
            "context_length": 400_000,
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "pricing": {"prompt": "0.0000001", "completion": "0.0000005"},
            "supported_parameters": ["structured_outputs"],
        },
        {
            "id": "minimax/minimax-m3.1-flash:free",
            "name": "MiniMax (free)",
            "context_length": 1_000_000,
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": [],
        },
        {"id": "broken/variable", "pricing": {"prompt": "-1", "completion": "x"}},
        {"name": "no id"},
        "not a model",
    ]
}


def test_search_finds_providers_by_name_alias_or_kind() -> None:
    assert [p.id for p in find("groq")] == ["groq"]
    assert [p.id for p in find("claude")] == ["anthropic"]
    assert {p.id for p in find("speech")} == {
        "elevenlabs",
        "deepgram",
        "assemblyai",
        "sarvam",
        "gladia",
        "speechmatics",
    }
    assert [p.id for p in find("hindi")] == ["sarvam"]
    assert find("  ") == list(PROVIDERS) and find("nothing like this") == []
    assert "custom" in BY_ID and BY_ID["custom"].compatible


def test_openrouter_rows_carry_context_inputs_json_and_prices() -> None:
    rows = {row["id"]: row for row in normalize_openrouter(OPENROUTER)}
    flash = rows["google/gemini-3.8-flash"]
    assert flash["context"] == 1_048_576 and flash["audio_in"] and flash["json"]
    assert (flash["usd_in_per_million"], flash["usd_out_per_million"]) == (0.75, 3.75)
    assert rows["openai/gpt-6-luna"]["json"] and not rows["openai/gpt-6-luna"]["audio_in"]
    assert rows["minimax/minimax-m3.1-flash:free"]["free"]
    variable = rows["broken/variable"]
    assert variable["usd_in_per_million"] is None and variable["usd_out_per_million"] is None
    assert len(rows) == 4
    assert normalize_openrouter(None) == [] and normalize_openrouter({"data": "x"}) == []


def test_each_provider_lists_its_models_and_what_the_pipeline_runs_on_them() -> None:
    openrouter = normalize_openrouter(OPENROUTER)
    gemini = {row["id"]: row for row in models_for(BY_ID["gemini"], openrouter)}
    flash = gemini["google/gemini-3.8-flash"]
    assert set(flash["stages"]) >= {"Facts", "Report and coaching"}
    assert "openai/gpt-6-luna" not in gemini
    # Speech comes from the price sheet and the registry: priced per hour of audio.
    (scribe,) = [row for row in models_for(BY_ID["elevenlabs"], openrouter)]
    assert scribe["id"] == "scribe_v2" and scribe["audio_in"]
    assert scribe["usd_per_audio_hour"] and scribe["stages"] == ["Transcription"]
    # OpenRouter itself offers every model it lists.
    assert len(models_for(BY_ID["openrouter"], openrouter)) == 4
    # A provider OpenRouter does not list shows its registry models until its key is added.
    groq = models_for(BY_ID["groq"], openrouter)
    assert groq and all(row["source"] == "registry" for row in groq)
    assert models_for(BY_ID["gladia"], openrouter) == []
    # The shared catalogue rows are never changed by a provider's view.
    assert normalize_openrouter(OPENROUTER)[0]["stages"] == []
    assert pipeline_state(BY_ID["gemini"]) == "ready"
    assert pipeline_state(BY_ID["anthropic"]) == "planned"
    assert pipeline_state(BY_ID["mistral"]) == "none"


def test_the_hub_lists_every_provider_and_one_providers_models() -> None:
    openrouter = normalize_openrouter(OPENROUTER)
    view = hub_view(openrouter, fetched_at=NOW, problem=None, selected="gemini")
    assert [row["id"] for row in view["providers"]] == [p.id for p in PROVIDERS]
    gemini = next(row for row in view["providers"] if row["id"] == "gemini")
    assert gemini["pipeline"] == "ready" and gemini["pipeline_models"] >= 1
    assert gemini["cheapest_in_per_million"] == 0.75
    assert view["selected"] == "gemini" and view["models"]
    assert view["catalogue"] == {
        "source": "OpenRouter",
        "fetched_at": NOW.isoformat(),
        "problem": None,
    }
    assert view["fx"]["usd_to_inr"] == 100
    nothing = hub_view([], fetched_at=None, problem="down", selected=None)
    assert nothing["selected"] is None and nothing["models"] == []
    assert nothing["catalogue"]["problem"] == "down"


async def test_the_catalogue_is_read_every_six_hours_and_kept_when_a_read_fails() -> None:
    calls: list[str] = []

    async def fetch(url: str) -> Any:
        calls.append(url)
        return OPENROUTER

    async def broken(url: str) -> Any:
        raise OSError("offline")

    catalogue = OpenRouterCatalogue()
    await catalogue.read(broken, NOW)
    assert catalogue.models == [] and catalogue.problem
    await catalogue.read(fetch, NOW)
    assert len(catalogue.models) == 4 and catalogue.problem is None
    await catalogue.read(fetch, NOW + timedelta(hours=1))
    assert len(calls) == 1  # still fresh
    await catalogue.read(broken, NOW + REFRESH + timedelta(minutes=1))
    assert len(catalogue.models) == 4 and catalogue.problem  # the last good copy stays

    async def empty(url: str) -> Any:
        return {"data": []}

    later = OpenRouterCatalogue()
    await later.read(empty, NOW)
    assert later.models == [] and later.problem == "OpenRouter's catalogue came back empty."
