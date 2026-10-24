"""Which of a business's stages each ad platform hears about, and under what name.

The engine suggests a match for every stage (from the stage's meaning and words, and
the platform's own events); the manager sees each match in plain words and confirms
it with one tap. Only confirmed matches are sent. A stage added later shows as a new
suggestion and is not sent until it is confirmed too.

Kept in the organisation's Lead Desk settings under ``ad_sync``::

    {"cursor": {"at": ..., "id": ...},
     "providers": {"meta": {"destination": {"id": ..., "name": ...}, "on": true,
                            "events": {"<stage key>": "<event name>" | null},
                            "confirmed_at": <epoch>, "confirmed_by": "<person>",
                            "test_code": null, "since": <epoch>}}}

The Meta-only settings from before (``meta_conversions``) are read as Meta's, with the
desk's six stages as the confirmed matches, and moved here on the first save.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import ModuleType
from typing import Any, Final, Literal
from uuid import UUID

from ac_platform.lead_desk.journey.model import Journey, JourneyError, Stage
from ac_platform.lead_desk.journey.providers import PROVIDERS, Spec
from ac_platform.lead_desk.journey.providers import google_ads as google_provider
from ac_platform.lead_desk.journey.providers import linkedin as linkedin_provider
from ac_platform.lead_desk.journey.providers import meta as meta_provider
from ac_platform.lead_desk.journey.providers import microsoft_ads as microsoft_provider
from ac_platform.lead_desk.journey.providers import tiktok as tiktok_provider

KEY: Final[str] = "ad_sync"
LEGACY_META: Final[str] = "meta_conversions"
MODULES: Final[dict[str, ModuleType]] = {
    "meta": meta_provider,
    "google_ads": google_provider,
    "linkedin": linkedin_provider,
    "tiktok": tiktok_provider,
    "microsoft_ads": microsoft_provider,
}

MatchState = Literal["on", "off", "new"]


def module(provider: str) -> ModuleType:
    found = MODULES.get(provider)
    if found is None:
        raise JourneyError("That ad platform isn't available yet.")
    return found


def spec(provider: str) -> Spec:
    value: Spec = module(provider).SPEC
    return value


def available() -> tuple[str, ...]:
    return tuple(provider for provider in PROVIDERS if provider in MODULES)


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    provider: str
    destination_id: str | None
    destination_name: str | None
    on: bool
    events: dict[str, str | None]  # confirmed matches only
    confirmed_at: int | None
    confirmed_by: str | None
    test_code: str | None
    since: int
    extra: dict[str, Any] = field(default_factory=dict)  # e.g. Google's conversion actions

    @property
    def ready(self) -> bool:
        return self.on and bool(self.destination_id) and bool(self.events)


def _legacy_meta(config: Mapping[str, Any]) -> ProviderSettings | None:
    value = config.get(LEGACY_META)
    if not isinstance(value, Mapping) or not value.get("dataset_id"):
        return None
    events = value.get("events") if isinstance(value.get("events"), Mapping) else {}
    return ProviderSettings(
        provider="meta",
        destination_id=str(value["dataset_id"]),
        destination_name=str(value.get("dataset_name") or value["dataset_id"])[:120],
        on=value.get("on") is True,
        events={str(k): (str(v) if v else None) for k, v in (events or {}).items()},
        confirmed_at=int(value.get("at") or 0) or None,
        confirmed_by=str(value["by"]) if value.get("by") else None,
        test_code=value["test_code"] if isinstance(value.get("test_code"), str) else None,
        since=int(value.get("since") or 0),
    )


def read(config: Mapping[str, Any], provider: str) -> ProviderSettings:
    box = config.get(KEY)
    providers = box.get("providers") if isinstance(box, Mapping) else None
    value = providers.get(provider) if isinstance(providers, Mapping) else None
    if not isinstance(value, Mapping):
        legacy = _legacy_meta(config) if provider == "meta" else None
        return legacy or ProviderSettings(provider, None, None, False, {}, None, None, None, 0)
    raw = value.get("destination")
    destination: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    events = value.get("events") if isinstance(value.get("events"), Mapping) else {}
    return ProviderSettings(
        provider=provider,
        destination_id=str(destination["id"]) if destination.get("id") else None,
        destination_name=str(destination.get("name") or destination.get("id") or "")[:120] or None,
        on=value.get("on") is True,
        events={str(k): (str(v) if v else None) for k, v in (events or {}).items()},
        confirmed_at=int(value["confirmed_at"]) if value.get("confirmed_at") else None,
        confirmed_by=str(value["confirmed_by"]) if value.get("confirmed_by") else None,
        test_code=value["test_code"] if isinstance(value.get("test_code"), str) else None,
        since=int(value.get("since") or 0),
        extra=dict(value["extra"]) if isinstance(value.get("extra"), Mapping) else {},
    )


def cursor(config: Mapping[str, Any]) -> tuple[datetime, UUID] | None:
    """Where collecting got to: the last Lead Desk event read (time, id)."""
    box = config.get(KEY)
    value = box.get("cursor") if isinstance(box, Mapping) else None
    if value is None:
        legacy = config.get(LEGACY_META)
        value = legacy.get("cursor") if isinstance(legacy, Mapping) else None
    if not isinstance(value, Mapping):
        return None
    try:
        return datetime.fromisoformat(str(value["at"])), UUID(str(value["id"]))
    except (KeyError, ValueError):
        return None


def any_on(config: Mapping[str, Any]) -> bool:
    return any(read(config, provider).ready for provider in available())


def _write(config: Mapping[str, Any], provider: str, settings: ProviderSettings) -> dict[str, Any]:
    out = dict(config)
    box = dict(out.get(KEY) or {}) if isinstance(out.get(KEY), Mapping) else {}
    if "cursor" not in box:
        legacy = config.get(LEGACY_META)
        if isinstance(legacy, Mapping) and isinstance(legacy.get("cursor"), Mapping):
            box["cursor"] = dict(legacy["cursor"])
    providers = dict(box.get("providers") or {})
    if provider == "meta" and "meta" not in providers and _legacy_meta(config) is not None:
        # Moved here: the old sender's settings stay as a record, marked as moved.
        out[LEGACY_META] = {**dict(config[LEGACY_META]), "on": False, "moved": True}
    providers[provider] = {
        "destination": {"id": settings.destination_id, "name": settings.destination_name}
        if settings.destination_id
        else None,
        "on": settings.on,
        "events": settings.events,
        "confirmed_at": settings.confirmed_at,
        "confirmed_by": settings.confirmed_by,
        "test_code": settings.test_code,
        "since": settings.since,
        "extra": settings.extra,
    }
    box["providers"] = providers
    out[KEY] = box
    return out


def with_cursor(config: Mapping[str, Any], at: datetime, event: UUID) -> dict[str, Any]:
    out = dict(config)
    box = dict(out.get(KEY) or {}) if isinstance(out.get(KEY), Mapping) else {}
    box["cursor"] = {"at": at.isoformat(), "id": str(event)}
    out[KEY] = box
    return out


# ----- matching -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Match:
    stage: Stage
    suggested: str | None
    saved: str | None
    state: MatchState  # on: sent as `saved`; off: not sent; new: not confirmed yet


def suggestions(provider: str, journey: Journey) -> dict[str, str | None]:
    """The engine's match for every live stage, or None to send nothing for it."""
    suggest = module(provider).suggest
    out: dict[str, str | None] = {}
    used: set[str] = set()
    for stage in journey.live:
        # Junk (fake or unusable) means nothing to an ad platform's buyers: never sent
        # unless a manager picks an event for it.
        name = None if stage.kind == "junk" else suggest(stage)
        # One event name per stage: a later stage with the same name is left out.
        if name is not None and name.casefold() in used:
            name = None
        if name is not None:
            used.add(name.casefold())
        out[stage.key] = name
    return out


def matches(provider: str, journey: Journey, settings: ProviderSettings) -> list[Match]:
    suggested = suggestions(provider, journey)
    out: list[Match] = []
    for stage in journey.live:
        if stage.key in settings.events:
            saved = settings.events[stage.key]
            out.append(Match(stage, suggested.get(stage.key), saved, "on" if saved else "off"))
        else:
            out.append(Match(stage, suggested.get(stage.key), None, "new"))
    return out


def clean_events(
    provider: str, journey: Journey, events: Mapping[str, Any]
) -> dict[str, str | None]:
    """The matches a manager confirmed, checked: live stages only, names the platform
    accepts, one stage per name."""
    info = spec(provider)
    out: dict[str, str | None] = {}
    live = {stage.key for stage in journey.live}
    for key, name in events.items():
        if key not in live:
            continue
        if name is None or (isinstance(name, str) and not name.strip()):
            out[key] = None
            continue
        if not isinstance(name, str):
            raise JourneyError("Pick a name for each stage, or leave it off.")
        value = name.strip()
        if info.naming == "stage":
            if not info.name_pattern.fullmatch(value):
                raise JourneyError(
                    "Use up to 50 letters, numbers, spaces, dots, dashes or underscores for "
                    "each name."
                )
        elif info.option(value) is None:
            raise JourneyError(f"Pick one of the listed {info.name} events for each stage.")
        out[key] = value
    names = [name.casefold() for name in out.values() if name]
    if len(set(names)) != len(names):
        raise JourneyError("Give each stage its own name.")
    return out


def confirmed(
    config: Mapping[str, Any],
    provider: str,
    journey: Journey,
    events: Mapping[str, Any],
    *,
    by: UUID,
    now: int,
) -> dict[str, Any]:
    """The matches as confirmed: every live stage the page sent, merged over the ones
    confirmed before (a stage left out keeps its earlier match)."""
    before = read(config, provider)
    merged = {**before.events, **clean_events(provider, journey, events)}
    live = {stage.key for stage in journey.stages}
    merged = {key: value for key, value in merged.items() if key in live}
    settings = ProviderSettings(
        provider=provider,
        destination_id=before.destination_id,
        destination_name=before.destination_name,
        on=before.on,
        events=merged,
        confirmed_at=now,
        confirmed_by=str(by),
        test_code=before.test_code,
        since=before.since,
        extra=before.extra,
    )
    return _write(config, provider, settings)


def destination_saved(
    config: Mapping[str, Any],
    provider: str,
    *,
    destination_id: str,
    destination_name: str,
    on: bool,
    test_code: str | None,
    now: int,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Where the platform's events go, and whether they go. Turning sending on, or a new
    destination, starts from now: earlier stages are never sent."""
    module(provider)
    before = read(config, provider)
    fresh = before.destination_id != destination_id or (on and not before.on)
    settings = ProviderSettings(
        provider=provider,
        destination_id=destination_id,
        destination_name=destination_name.strip()[:120] or destination_id,
        on=on,
        events=before.events,
        confirmed_at=before.confirmed_at,
        confirmed_by=before.confirmed_by,
        test_code=test_code,
        since=now if fresh or not before.since else before.since,
        extra={**({} if fresh else before.extra), **dict(extra or {})},
    )
    return _write(config, provider, settings)


async def is_connected(provider: str, db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> bool:
    """Whether the business connected this platform (some need the database to tell)."""
    adapter = module(provider)
    check = getattr(adapter, "connected_in", None)
    if check is not None:
        return bool(await check(db, tenant_id, config))
    return bool(adapter.connected(config, tenant_id))


def with_extra(settings: ProviderSettings, extra: Mapping[str, Any]) -> ProviderSettings:
    return replace(settings, extra={**settings.extra, **dict(extra)})


def epoch(at: datetime | None = None) -> int:
    return int((at or datetime.now(UTC)).timestamp())
