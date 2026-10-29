"""Small dependency-free CPU probability model and temporal evaluation.

No text, identity or seller features. Call outcomes must be independent of duration.
Snapshots and their labels are supplied by a logged, owner-tenant-only CRM export.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

AC_TENANT = "02150758-5316-46bb-975b-4cd0f0041df2"
TASKS = ("junk", "next_best_lead", "call_classifier")
FEATURES = {
    "junk": ("attempts", "failed_attempts", "days_since_connected", "age_days"),
    "next_best_lead": ("attempts", "failed_attempts", "days_since_connected", "hour"),
    "call_classifier": ("duration_seconds",),
}
BINS = {"duration_seconds": 9, "hour": 7, "attempts": 7, "failed_attempts": 7,
        "days_since_connected": 8, "age_days": 8}


def moment(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include timezone")
    return result


def tenant_allowlist(ea_tenant: str | None = None) -> frozenset[str]:
    """EA's full UUID must be supplied from the orchestrator's source receipt."""
    allowed = {AC_TENANT}
    if ea_tenant is not None:
        if str(UUID(ea_tenant)) != ea_tenant or not ea_tenant.startswith("62562d4d-"):
            raise ValueError("EA full tenant UUID does not match owner order")
        allowed.add(ea_tenant)
    return frozenset(allowed)


@dataclass(frozen=True)
class Example:
    tenant: str
    lead: str
    at: str
    label_at: str
    label: int
    features: dict[str, float]
    # Separate event/snapshot identifier prevents duplicate weighting.
    event: str


def validate(rows: list[Example], task: str, allowed: frozenset[str]) -> None:
    if task not in TASKS:
        raise ValueError("unknown task")
    seen = set()
    for row in rows:
        if row.tenant not in allowed:
            raise ValueError("non-owner tenant: entire input refused")
        if row.label not in (0, 1) or isinstance(row.label, bool):
            raise ValueError("binary integer labels required")
        if not row.lead or not row.event:
            raise ValueError("pseudonymous lead and event keys required")
        key = (row.tenant, row.event)
        if key in seen:
            raise ValueError("duplicate event/snapshot")
        seen.add(key)
        if moment(row.label_at) < moment(row.at):
            raise ValueError("label precedes snapshot")
        if set(row.features) != set(FEATURES[task]):
            raise ValueError("only the documented task features are permitted")
        if any(not math.isfinite(v) or v < 0 for v in row.features.values()):
            raise ValueError("features must be finite and nonnegative")
        if "hour" in row.features and not 0 <= row.features["hour"] < 24:
            raise ValueError("hour must be UTC in [0,24)")


def split(rows: list[Example], cutoff: str) -> tuple[list[Example], list[Example], int]:
    """Purge train labels unavailable at cutoff. Strictly later snapshots form test."""
    boundary = moment(cutoff)
    train = [r for r in rows if moment(r.at) < boundary and moment(r.label_at) < boundary]
    test = [r for r in rows if moment(r.at) >= boundary]
    return train, test, len(rows) - len(train) - len(test)


def bucket(name: str, value: float) -> str:
    edges = {
        "duration_seconds": (0, 3, 7, 8, 15, 30, 60, 180),
        "hour": (5, 8, 11, 14, 17, 20),
        "attempts": (0, 1, 2, 3, 5, 10),
        "failed_attempts": (0, 1, 2, 3, 5, 10),
        "days_since_connected": (0, 1, 3, 7, 14, 30, 90),
        "age_days": (0, 1, 3, 7, 14, 30, 90),
    }[name]
    return str(sum(value > edge for edge in edges))


class ProbabilityModel:
    """Laplace-smoothed categorical naive Bayes; no fitted threshold on test data."""

    def __init__(self, task: str) -> None:
        self.task = task
        self.counts = [0, 0]
        self.cells: dict[tuple[int, str, str], int] = defaultdict(int)

    def fit(self, rows: list[Example]) -> ProbabilityModel:
        if not rows or len({r.label for r in rows}) < 2:
            raise ValueError("training requires both independently labelled classes")
        self.counts = [0, 0]
        self.cells.clear()
        for row in rows:
            self.counts[row.label] += 1
            for name in FEATURES[self.task]:
                self.cells[row.label, name, bucket(name, row.features[name])] += 1
        return self

    def predict(self, features: dict[str, float]) -> float:
        if not sum(self.counts):
            raise ValueError("model is not fitted")
        logs = [math.log((n + 1) / (sum(self.counts) + 2)) for n in self.counts]
        for label in (0, 1):
            for name in FEATURES[self.task]:
                # Fixed bins, including unseen values; denominator never fitted on test.
                bins = BINS[name]
                cell = self.cells.get((label, name, bucket(name, features[name])), 0)
                logs[label] += math.log((cell + 1) / (self.counts[label] + bins))
        delta = max(-700.0, min(700.0, logs[0] - logs[1]))
        return 1 / (1 + math.exp(delta))

    def state(self) -> dict[str, Any]:
        return {"task": self.task, "counts": self.counts,
                "cells": [[*key, value] for key, value in sorted(self.cells.items())]}


def baseline(task: str, features: dict[str, float], ring_seconds: float = 8) -> float:
    if task == "junk":
        return float(features["failed_attempts"] >= 3)
    if task == "next_best_lead":
        # Explicit provisional comparator: fewest past attempts first.
        return 1 / (1 + features["attempts"])
    return float(features["duration_seconds"] > ring_seconds)


def metrics(labels: list[int], probabilities: list[float]) -> dict[str, float | int | None]:
    predicted = [p >= 0.5 for p in probabilities]
    tp = sum(y == 1 and p for y, p in zip(labels, predicted, strict=True))
    fp = sum(y == 0 and p for y, p in zip(labels, predicted, strict=True))
    fn = sum(y == 1 and not p for y, p in zip(labels, predicted, strict=True))
    n = len(labels)
    return {"n": n, "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "brier": sum((y-p)**2 for y, p in zip(labels, probabilities, strict=True))/n
            if n else None}


def intervals(rows: list[Example], scores: list[float], repeats: int = 300) -> dict[str, Any]:
    """95% percentile bootstrap by tenant/lead, preserving correlated attempts."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[row.tenant, row.lead].append(i)
    keys = sorted(groups)
    rng = random.Random(29)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(repeats if len(keys) >= 2 else 0):
        indices = [i for _ in keys for i in groups[rng.choice(keys)]]
        result = metrics([rows[i].label for i in indices], [scores[i] for i in indices])
        for name in ("precision", "recall", "brier"):
            value = result[name]
            if value is not None:
                samples[name].append(float(value))
    output = {}
    for name in ("precision", "recall", "brier"):
        values = sorted(samples[name])
        output[name] = ([values[int(0.025 * (len(values)-1))],
                         values[int(0.975 * (len(values)-1))]] if values else None)
    return {"method": "95% lead-cluster percentile bootstrap, seed 29",
            "repeats": repeats, "clusters": len(keys), "intervals": output}


def ranking(rows: list[Example], scores: list[float], k: int = 5) -> dict[str, Any]:
    """Retrospective ranking among attempted leads in each tenant/hour only."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[row.tenant, moment(row.at).strftime("%Y-%m-%dT%H")].append(i)
    # One candidate per lead/hour, earliest attempt; ties resolved without labels.
    selected = []
    eligible_positive = 0
    for indices in groups.values():
        unique: dict[str, int] = {}
        for i in sorted(indices, key=lambda j: (moment(rows[j].at), rows[j].event)):
            unique.setdefault(rows[i].lead, i)
        candidates = list(unique.values())
        eligible_positive += sum(rows[i].label for i in candidates)
        selected.extend(sorted(candidates, key=lambda i: (-scores[i], rows[i].event))[:k])
    hits = sum(rows[i].label for i in selected)
    return {"k": k, "hours": len(groups), "selected": len(selected),
            "precision_at_k": hits / len(selected) if selected else None,
            "recall_at_k": hits / eligible_positive if eligible_positive else None,
            "limit": "attempted candidates only; no causal connection lift claim"}
