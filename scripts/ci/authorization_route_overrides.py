"""Per-route request fixtures the generic synthesiser cannot derive.

Each override is keyed by ``"METHOD /path"`` and may narrow by actor or
context.  Values: ``json`` (body), ``content``/``content_type`` (raw body),
``headers``, ``query``, ``path`` (fully resolved), ``etag_from`` (a GET whose
ETag feeds ``If-Match``; ``etag_json`` names a nested field) or ``skip`` (a
reason that records the row as unproven).  Callables receive the resources.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scripts.ci.authorization_fixtures import command_uuid, stable_uuid

Override = dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]


def _telemetry(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "json": {
            "events": [
                {
                    "event_id": str(stable_uuid("telemetry-event")),
                    "event_name": "gate.observed",
                    "occurred_at": "2026-01-15T09:00:00Z",
                    "session_id": str(stable_uuid("telemetry-session")),
                }
            ]
        }
    }


def _coaching_context(resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "json": {
            "command_id": command_uuid("coaching-context"),
            "focus_skill_id": "gate-skill",
            "mission_origin_submission_id": str(resources.get("submission_id", stable_uuid("x"))),
            "context": "Gate context note",
        }
    }


def _coaching_feedback(resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "json": {
            "command_id": command_uuid("coaching-feedback"),
            "agreement": "agree",
            "focus_skill_id": "gate-skill",
            "mission_origin_submission_id": str(resources.get("submission_id", stable_uuid("x"))),
        }
    }


STUDIO_ETAG = {
    "etag_from": "/v1/admin/studio/programs/{program_id}",
    "etag_json": "versions.0.etag",
}

OVERRIDES: dict[str, Override] = {
    "POST /v1/me/coaching/context": _coaching_context,
    "POST /v1/me/coaching/feedback": _coaching_feedback,
    "PUT /v1/me/coaching/sharing": {"json": {"shared": True, "expected_revision": 0}},
    "POST /v1/telemetry/batch": _telemetry,
    "POST /v1/telemetry/events": _telemetry,
    "POST /v1/analytics/events/batch": _telemetry,
    "POST /v1/conversation/acquisition/session": {"json": {"challenge_token": "gate-challenge"}},
    "POST /v1/media/uploads": {
        "json": {
            "purpose": "video",
            "filename": "gate.mp4",
            "content_type": "video/mp4",
            "content_length": 1000,
        }
    },
    "POST /v1/profile/avatar": {
        "json": {
            "purpose": "avatar",
            "filename": "gate.jpg",
            "content_type": "image/jpeg",
            "content_length": 1000,
        }
    },
    "PUT /v1/me/sales-xray-profile": {
        "json": {
            "full_name": "Gate Person",
            "phone_number_e164": "+15550100000",
            "expected_revision": 0,
        }
    },
    "PUT /v1/community/username": {"json": {"username": "gate_claimed"}},
    "PUT /v1/practice/profile": {"json": {"timezone": "Asia/Kolkata", "expected_revision": 0}},
    "POST /v1/admin/learners/lookup": {
        "json": {"query": "learner@example.test", "purpose": "learner_support"}
    },
    "POST /v1/admin/conversation-minute-accounts/resolve-target": {
        "json": {"query": "member@example.test"}
    },
    "PUT /v1/onboarding": {
        "headers": {"if-match": '"onboarding-revision-0"'},
        "json": {"status": "in_progress", "current_step": 1},
    },
    "PUT /v1/activities/{activity_id}/draft": {"headers": {"if-match": '"draft-revision-0"'}},
    "POST /v1/activities/{activity_id}/evidence": {
        "headers": {"if-match": '"activity-revision-0"'}
    },
    "POST /v1/admin/corrections": {"headers": {"if-match": '"submission-revision-0"'}},
    "POST /v1/admin/program-versions/{program_version_id}/publish": STUDIO_ETAG,
    "POST /v1/admin/studio/program-versions/{version_id}/modules": STUDIO_ETAG,
    "PATCH /v1/admin/studio/program-versions/{version_id}/modules/{module_id}": STUDIO_ETAG,
    "POST /v1/admin/studio/program-versions/{version_id}/modules/{module_id}/activities": STUDIO_ETAG,
    "PATCH /v1/admin/studio/program-versions/{version_id}/activities/{activity_id}": STUDIO_ETAG,
    "POST /v1/admin/studio/program-versions/{version_id}/revision": STUDIO_ETAG,
}
ACTOR_OVERRIDES: dict[tuple[str, str], Override] = {}


def override(
    method: str, path: str, actor: str, context: str, resources: dict[str, Any]
) -> dict[str, Any] | None:
    key = f"{method} {path}"
    value = (
        ACTOR_OVERRIDES.get((key, actor))
        or ACTOR_OVERRIDES.get((key, context))
        or OVERRIDES.get(key)
    )
    if value is None:
        return None
    return value(resources) if callable(value) else value
