"""As-of CRM feature/label construction from a logged, sanitised CRM extract.

Connection labels are supplied independently by the extract's reviewed mapping;
this code never derives them from duration. Unknown outcomes remain unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta

from ac_platform.decisions.core import Example, moment


@dataclass(frozen=True)
class Lead:
    tenant: str
    lead: str
    created_at: str


@dataclass(frozen=True)
class Attempt:
    tenant: str
    lead: str
    event: str
    at: str
    ended_at: str
    duration_seconds: float
    connected: int | None


@dataclass(frozen=True)
class Stage:
    tenant: str
    lead: str
    event: str
    at: str
    stage: str


def history(lead: Lead, at: str, attempts: list[Attempt]) -> dict[str, float]:
    boundary = moment(at)
    prior = [
        a
        for a in attempts
        if a.tenant == lead.tenant and a.lead == lead.lead and moment(a.ended_at) < boundary
    ]
    connections = [moment(a.ended_at) for a in prior if a.connected == 1]
    return {
        "attempts": float(len(prior)),
        "failed_attempts": float(sum(a.connected == 0 for a in prior)),
        "days_since_connected": (boundary - max(connections)).total_seconds() / 86400
        if connections
        else 365.0,
        "age_days": (boundary - moment(lead.created_at)).total_seconds() / 86400,
    }


def build_examples(
    leads: list[Lead],
    attempts: list[Attempt],
    stages: list[Stage],
    observed_until: str,
    horizon_days: int = 7,
) -> dict[str, list[Example]]:
    if horizon_days <= 0:
        raise ValueError("positive horizon required")
    end = moment(observed_until)
    output: dict[str, list[Example]] = {"junk": [], "next_best_lead": [], "call_classifier": []}
    lookup = {(lead.tenant, lead.lead): lead for lead in leads}
    if len(lookup) != len(leads):
        raise ValueError("duplicate lead")
    seen = set()
    for attempt in attempts:
        key = (attempt.tenant, attempt.event)
        if key in seen:
            raise ValueError("duplicate attempt")
        seen.add(key)
        if (attempt.tenant, attempt.lead) not in lookup:
            raise ValueError("attempt has no scoped lead")
        if moment(attempt.ended_at) < moment(attempt.at):
            raise ValueError("attempt ends before it starts")
        if attempt.connected not in (None, 0, 1):
            raise ValueError("connection label must be independent binary outcome or null")
    for stage in stages:
        if (stage.tenant, stage.lead) not in lookup:
            raise ValueError("stage has no scoped lead")
        if stage.stage not in {
            "new",
            "not_connected",
            "follow_up",
            "interested",
            "won",
            "lost",
            "junk",
        }:
            raise ValueError("unknown stage; source mapping needs review")
    for a in sorted(attempts, key=lambda a: (moment(a.at), a.event)):
        lead = lookup[a.tenant, a.lead]
        if moment(a.at) < moment(lead.created_at):
            raise ValueError("attempt precedes lead creation")
        if moment(a.ended_at) > end:
            continue
        h = history(lead, a.at, attempts)
        if a.connected is not None:
            next_features = {
                k: h[k] for k in ("attempts", "failed_attempts", "days_since_connected")
            }
            next_features["hour"] = float(moment(a.at).astimezone(UTC).hour)
            output["next_best_lead"].append(
                Example(a.tenant, a.lead, a.at, a.ended_at, a.connected, next_features, a.event)
            )
            output["call_classifier"].append(
                Example(
                    a.tenant,
                    a.lead,
                    a.ended_at,
                    a.ended_at,
                    a.connected,
                    {"duration_seconds": a.duration_seconds},
                    a.event,
                )
            )
        relevant = sorted(
            [
                s
                for s in stages
                if s.tenant == a.tenant and s.lead == a.lead and moment(s.at) <= end
            ],
            key=lambda s: (moment(s.at), s.event),
        )
        before = [s for s in relevant if moment(s.at) <= moment(a.at)]
        if before and before[-1].stage in {"junk", "lost", "won"}:
            continue
        horizon = moment(a.at) + timedelta(days=horizon_days)
        # Both positive and negative examples must mature: avoid differential censoring.
        if horizon > end:
            continue
        future = [s for s in relevant if moment(a.at) < moment(s.at) <= horizon]
        positives = [
            s
            for s in future
            if s.stage == "junk"
            or (s.stage == "lost" and history(lead, s.at, attempts)["failed_attempts"] >= 3)
        ]
        output["junk"].append(
            Example(a.tenant, a.lead, a.at, horizon.isoformat(), int(bool(positives)), h, a.event)
        )
    return output
