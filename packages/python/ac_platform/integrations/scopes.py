"""What an API key may do. A key holds one or more scopes; each route needs one."""

from __future__ import annotations

from collections.abc import Iterable

# Key -> the words the Integrations page shows.
SCOPES: dict[str, str] = {
    "calls:read": "Read calls and their status",
    "reports:read": "Read call reports and the facts found in calls",
    "leads:read": "Read leads",
    "leads:write": "Create and update leads",
    # AI writes (docs/product/ai-writes.md): each change an app may make is its own scope.
    "leads:notes": "Add notes to leads",
    "leads:tasks": "Add tasks and reminders to leads",
    "leads:update": "Change a lead's name, company, city, interest or language",
    "leads:stage": "Move a lead to another stage, with the reason",
    # An organisation's key held by an owner or admin only (ai-writes.md, "Amended 15 Nov").
    "leads:assign": "Give leads to a teammate",
    # The admin primitives (owner, 17 Nov 2026; integrations/admin_api.py): an organisation's
    # key held by an owner or admin only. The Bin's purge stays in Sales X-Ray.
    "leads:archive": "Archive leads, move them to the Bin and restore them",
    # The team as Sales X-Ray shows it: names, never emails (API gap 7, 15 Nov 2026).
    "team:read": "See the team: names, roles and lead capacity",
    "team:manage": "Invite people, change their roles and remove them",
    # Ask Dipak's coaching loop (14 Nov 2026): missions and their counts; the team's
    # for an organisation key or a role that sees the team.
    "coaching:read": "Read Next-call missions and on how many calls each was done",
    # A seller's call, sent by an organisation's key and analysed as it arrives (API gap 2,
    # 15 Nov 2026; integrations/recordings_api.py). Not calls:write, which is a person's
    # app inbox.
    "recordings:write": "Upload calls for a seller to analyse",
    "webhooks:manage": "Manage the webhook",
}
# Only an app a person connects may ask for these: they act as that person, which an
# organisation's API key never is (POST /v1/api/calls; integrations/app_uploads.py).
APP_SCOPES: dict[str, str] = {
    "calls:write": "Send call recordings for you to add to your calls",
    # Missions are a person's own (Ask Dipak, 14 Nov 2026).
    "coaching:write": "Save lessons, choose Next-call missions and answer them after calls",
}


class ScopeError(ValueError):
    pass


def validate(scopes: Iterable[object], *, app: bool = False) -> list[str]:
    """Known scopes only, at least one, sorted and without repeats; ``app`` also takes
    the scopes only a person's connected app may hold."""
    known = {**SCOPES, **APP_SCOPES} if app else SCOPES
    chosen = list(scopes)
    if not chosen or any(not isinstance(scope, str) or scope not in known for scope in chosen):
        raise ScopeError("scopes")
    return sorted(set(chosen))  # type: ignore[arg-type]


def public() -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in SCOPES.items()]
