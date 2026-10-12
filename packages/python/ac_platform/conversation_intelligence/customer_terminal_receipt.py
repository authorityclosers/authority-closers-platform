"""Immutable customer failure evidence, independent of provider-cost settlement.

A decoded receipt or a successful match grants no mutation, retry or access.
The database adapter must load its comparison facts from canonical records under
admission/usage locks, append the audit and settlement together, and serialize
against report publication. Never derive these facts from learner input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from .checkpoints import SourceBinding, require_sha256
from .entitlements import Snapshot


def _uuid(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"invalid {name}")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError(f"invalid {name}") from None
    if str(parsed) != value:
        raise ValueError(f"invalid {name}")


def _source(value: Any) -> SourceBinding:
    if not isinstance(value, dict) or set(value) != {
        "tenant_id",
        "recording_id",
        "source_sha256",
        "source_revision",
    }:
        raise ValueError("invalid customer failure source")
    return SourceBinding(**value)


@dataclass(frozen=True)
class CustomerTerminalFailureReceipt(Snapshot):
    source: SourceBinding
    usage_id: str
    submission_id: str
    duration_evidence_sha256: str
    reserved_seconds: int
    run_id: str
    recovery_generation: int
    failure_event_id: str
    failure_event_sha256: str
    completed_at_epoch: int

    _decoders: ClassVar[dict[str, Callable[[Any], Any]]] = {"source": _source}

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceBinding):
            raise ValueError("typed customer failure source required")
        # Revalidate nested objects at the receipt boundary.
        _source(
            {
                "tenant_id": self.source.tenant_id,
                "recording_id": self.source.recording_id,
                "source_sha256": self.source.source_sha256,
                "source_revision": self.source.source_revision,
            }
        )
        for name in ("usage_id", "submission_id", "run_id", "failure_event_id"):
            _uuid(getattr(self, name), name)
        _uuid(self.source.tenant_id, "tenant id")
        _uuid(self.source.recording_id, "recording id")
        require_sha256(self.duration_evidence_sha256, "duration evidence")
        require_sha256(self.failure_event_sha256, "failure event")
        if type(self.reserved_seconds) is not int or not 1 <= self.reserved_seconds <= 6000:
            raise ValueError("invalid reserved seconds")
        if type(self.recovery_generation) is not int or self.recovery_generation < 1:
            raise ValueError("invalid recovery generation")
        if type(self.completed_at_epoch) is not int or self.completed_at_epoch < 1:
            raise ValueError("invalid completion epoch")


def validate_terminal_failure_binding(
    receipt: CustomerTerminalFailureReceipt,
    canonical: CustomerTerminalFailureReceipt,
    *,
    run_state: str,
    task_state: str,
    report_published: bool,
) -> None:
    """Match independently loaded canonical facts; perform no persistence.

    The adapter must check current tenant/actor/source authority separately and
    build ``canonical`` from the locked usage, run and original failure event.
    ``report_published`` means a canonical delivered-report publication, not a
    metadata row or analytics event. Missing facts cannot become false defaults.
    Terminal evidence is not subject to the expired browser/provider permission
    window: that window governs new work, not accounting for failed work.
    """
    if not isinstance(receipt, CustomerTerminalFailureReceipt) or not isinstance(
        canonical, CustomerTerminalFailureReceipt
    ):
        raise ValueError("typed customer failure receipt required")
    receipt = CustomerTerminalFailureReceipt.from_dict(receipt.as_dict())
    canonical = CustomerTerminalFailureReceipt.from_dict(canonical.as_dict())
    if receipt != canonical:
        raise ValueError("customer terminal failure binding mismatch")
    if run_state != "failed" or task_state not in {"failed", "uncertain"}:
        raise ValueError("canonical terminal failure required")
    if type(report_published) is not bool or report_published:
        raise ValueError("customer failure conflicts with report publication")
