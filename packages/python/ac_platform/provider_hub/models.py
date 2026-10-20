"""The models each provider offers, for Admin's Providers hub.

Three sources, merged per provider:
- OpenRouter's public model catalogue (no key): context size, input and output modalities,
  structured-output support and list prices for hundreds of models, matched to a provider by
  model-id prefix ("google/" is Gemini). Read at most every six hours and kept in memory.
- the provider registry: which models the analysis pipeline can call today, and for which
  stage (transcription, facts, report and coaching).
- the price sheet: the unit prices our own cost figures use (speech is priced per hour or
  minute of audio there).
- the provider's own list, once its key is added here and tested (``keys.LISTED``): models
  OpenRouter does not list (Groq, Together, the speech providers) appear with their ids.

Prices are list prices in US dollars; nothing here is a charge or a quote.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from ac_platform.conversation_intelligence.admin_pricing import (
    FX_SET_ON,
    FX_USD_TO_INR,
    PRICING_SNAPSHOTS,
)
from ac_platform.conversation_intelligence.provider_registry import DEFAULT_PROVIDER_CATALOG
from ac_platform.provider_hub.catalogue import BY_ID, KIND_LABEL, PROVIDERS, Provider

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
REFRESH = timedelta(hours=6)
# The stages a registry task feeds, in Admin's words.
TASK_STAGE = {"asr": "Transcription", "facts": "Facts", "coaching": "Report and coaching"}
REGISTRY = {entry.provider_id: entry for entry in DEFAULT_PROVIDER_CATALOG.providers}
SCHEMA = "ac.admin.provider-hub/1"

Fetch = Callable[[str], Awaitable[Any]]


def _per_million(value: Any) -> float | None:
    """OpenRouter's dollars per token as dollars per million; None when variable or unknown."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number < 0 else round(number * 1_000_000, 4)


def normalize_openrouter(document: Any) -> list[dict[str, Any]]:
    """OpenRouter's catalogue as model rows; anything malformed is skipped."""

    data = document.get("data") if isinstance(document, Mapping) else None
    rows: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            continue
        architecture = item.get("architecture")
        architecture = architecture if isinstance(architecture, Mapping) else {}
        inputs = [m for m in architecture.get("input_modalities") or [] if isinstance(m, str)]
        outputs = [m for m in architecture.get("output_modalities") or [] if isinstance(m, str)]
        pricing = item.get("pricing")
        pricing = pricing if isinstance(pricing, Mapping) else {}
        params = {p for p in item.get("supported_parameters") or [] if isinstance(p, str)}
        context = item.get("context_length")
        usd_in = _per_million(pricing.get("prompt"))
        usd_out = _per_million(pricing.get("completion"))
        rows.append(
            {
                "id": item["id"],
                "name": str(item.get("name") or item["id"]),
                "context": context if type(context) is int and context > 0 else None,
                "inputs": inputs,
                "outputs": outputs,
                "audio_in": "audio" in inputs,
                "json": bool(params & {"structured_outputs", "response_format"}),
                "usd_in_per_million": usd_in,
                "usd_out_per_million": usd_out,
                "usd_per_audio_hour": None,
                "free": usd_in == 0 and usd_out == 0,
                "stages": [],
                "source": "openrouter",
            }
        )
    return rows


class OpenRouterCatalogue:
    """OpenRouter's catalogue, read at most every six hours; the last good copy on failure."""

    def __init__(self) -> None:
        self.models: list[dict[str, Any]] = []
        self.fetched_at: datetime | None = None
        self.problem: str | None = None

    async def read(self, fetch: Fetch, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        if self.fetched_at is not None and now - self.fetched_at < REFRESH:
            return
        try:
            models = normalize_openrouter(await fetch(OPENROUTER_MODELS))
        except Exception:  # noqa: BLE001 - a catalogue that can't be read is shown as such
            self.problem = "OpenRouter's catalogue could not be read just now."
            return
        if not models:
            self.problem = "OpenRouter's catalogue came back empty."
            return
        self.models, self.fetched_at, self.problem = models, now, None


CATALOGUE = OpenRouterCatalogue()


def _sheet_rows(registry_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (provider, model), snapshot in PRICING_SNAPSHOTS.items():
        if provider != registry_id:
            continue
        per_hour = snapshot.usd_per_hour
        if per_hour is None and snapshot.usd_per_minute is not None:
            per_hour = snapshot.usd_per_minute * 60
        rows.append(
            {
                "id": model,
                "name": model,
                "context": None,
                "inputs": ["audio"] if per_hour is not None else ["text"],
                "outputs": ["text"],
                "audio_in": per_hour is not None,
                "json": False,
                "usd_in_per_million": None
                if snapshot.input_usd_per_million_tokens is None
                else float(snapshot.input_usd_per_million_tokens),
                "usd_out_per_million": None
                if snapshot.output_usd_per_million_tokens is None
                else float(snapshot.output_usd_per_million_tokens),
                "usd_per_audio_hour": None if per_hour is None else float(per_hour),
                "free": False,
                "stages": [],
                "source": "price_sheet",
            }
        )
    return rows


def models_for(
    provider: Provider,
    openrouter: Iterable[dict[str, Any]],
    listed: Mapping[str, Sequence[str]] | None = None,
) -> list[dict[str, Any]]:
    """One provider's models: OpenRouter's by prefix, then the price sheet's, the registry's
    and the provider's own list (from its key's test), each marked with the stages the
    pipeline can run on it today."""

    if "*" in provider.prefixes:
        rows = [dict(row) for row in openrouter]
    else:
        rows = [
            dict(row)
            for row in openrouter
            if any(row["id"].startswith(prefix) for prefix in provider.prefixes)
        ]
    by_short = {row["id"].split("/", 1)[-1]: row for row in rows}
    registry = REGISTRY.get(provider.registry_id or "")
    if provider.registry_id:
        for sheet in _sheet_rows(provider.registry_id):
            known = by_short.get(sheet["id"])
            if known is None:
                rows.append(sheet)
                by_short[sheet["id"]] = sheet
            elif known["usd_per_audio_hour"] is None:
                known["usd_per_audio_hour"] = sheet["usd_per_audio_hour"]
    for model in registry.models if registry is not None else ():
        stages = [
            TASK_STAGE[task]
            for task, status in model.task_support
            if status == "implemented" and task in TASK_STAGE
        ]
        row = by_short.get(model.model_id) or by_short.get(model.model_id.split("/", 1)[-1])
        if row is None:
            row = {
                "id": model.model_id,
                "name": model.model_id,
                "context": None,
                "inputs": ["audio"] if "Transcription" in stages else ["text"],
                "outputs": ["text"],
                "audio_in": "Transcription" in stages,
                "json": False,
                "usd_in_per_million": None,
                "usd_out_per_million": None,
                "usd_per_audio_hour": None,
                "free": False,
                "stages": [],
                "source": "registry",
            }
            rows.append(row)
            by_short[model.model_id] = row
        row["stages"] = sorted(set(row["stages"]) | set(stages))
    for model_id in (listed or {}).get(provider.id, ()):
        if model_id in by_short or any(item["id"] == model_id for item in rows):
            continue
        by_short[model_id] = {
            "id": model_id,
            "name": model_id,
            "context": None,
            "inputs": [],
            "outputs": [],
            "audio_in": False,
            "json": False,
            "usd_in_per_million": None,
            "usd_out_per_million": None,
            "usd_per_audio_hour": None,
            "free": False,
            "stages": [],
            "source": "provider",
        }
        rows.append(by_short[model_id])
    return rows


def pipeline_state(provider: Provider) -> str:
    """'ready': the pipeline can call it today; 'planned': an adapter is designed, not built;
    'none': not wired to the pipeline (models can still be browsed and compared)."""

    registry = REGISTRY.get(provider.registry_id or "")
    if registry is None:
        return "none"
    return "ready" if registry.status == "implemented" else "planned"


def hub_view(
    openrouter: list[dict[str, Any]],
    *,
    fetched_at: datetime | None,
    problem: str | None,
    selected: str | None,
    listed: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    providers = []
    for provider in PROVIDERS:
        models = models_for(provider, openrouter, listed)
        prices = [
            row["usd_in_per_million"]
            for row in models
            if row["usd_in_per_million"] is not None and not row["free"]
        ]
        providers.append(
            {
                "id": provider.id,
                "name": provider.name,
                "kind": provider.kind,
                "kind_label": KIND_LABEL[provider.kind],
                "blurb": provider.blurb,
                "console": provider.console or None,
                "compatible": provider.compatible,
                "aliases": list(provider.aliases),
                "pipeline": pipeline_state(provider),
                "models": len(models),
                "pipeline_models": sum(1 for row in models if row["stages"]),
                "cheapest_in_per_million": min(prices) if prices else None,
            }
        )
    chosen = BY_ID.get(selected or "")
    return {
        "schema": SCHEMA,
        "providers": providers,
        "selected": chosen.id if chosen else None,
        "models": models_for(chosen, openrouter, listed) if chosen else [],
        "catalogue": {
            "source": "OpenRouter",
            "fetched_at": None if fetched_at is None else fetched_at.isoformat(),
            "problem": problem,
        },
        "fx": {"usd_to_inr": float(FX_USD_TO_INR), "set_on": FX_SET_ON.isoformat()},
    }
