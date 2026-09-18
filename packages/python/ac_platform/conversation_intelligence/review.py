"""Dual review proposals, cursor imports and explicit promotion evidence validation.

The AC application supplies authenticated actors, persisted assignments, run revisions
and approved gates. Client-supplied names, hashes or booleans are not authorization.
Nothing here writes a label, trains a model, changes a profile or promotes a release.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .checkpoints import canonical, content_hash, require_sha256, require_text

LANE_TARGETS = {
    "sales": frozenset({"context", "profile", "judge"}),
    "signal": frozenset({"transcript", "measurement", "attribution", "alignment"}),
}
LANE_RESPONSIBILITIES = {
    "sales": "Dipak: contextual and sales adjudication",
    "signal": "Suyash: measurement and attribution validation",
}
REVIEW_KINDS = frozenset({"correction", "reject", "question", "adjudication", "approve"})


@dataclass(frozen=True)
class RunBinding:
    tenant_id: str
    run_id: str
    run_revision: str
    transcript_revision: str
    measurement_revision: str
    profile_revision: str

    def __post_init__(self) -> None:
        for field, value in asdict(self).items():
            require_text(value, field)


@dataclass(frozen=True)
class ReviewAssignment:
    binding: RunBinding
    reviewer_id: str
    lane: str
    assignment_ref: str

    def __post_init__(self) -> None:
        require_text(self.reviewer_id, "reviewer id")
        require_text(self.assignment_ref, "assignment reference")
        if self.lane not in LANE_TARGETS:
            raise ValueError("unknown review lane")


@dataclass(frozen=True)
class ReviewProposal:
    """Canonical frozen content for append-only storage; sensitive payload stays private."""

    body_json: str

    def __post_init__(self) -> None:
        body = json.loads(self.body_json)
        if not isinstance(body, dict) or canonical(body).decode() != self.body_json:
            raise ValueError("review proposal must be canonical object JSON")

    @property
    def proposal_hash(self) -> str:
        return content_hash(json.loads(self.body_json))

    def as_dict(self) -> dict[str, Any]:
        return {**json.loads(self.body_json), "proposal_hash": self.proposal_hash}


def validate_review_proposal(
    payload: dict[str, Any],
    *,
    binding: RunBinding,
    assignment: ReviewAssignment,
    reviewer_id: str,
) -> ReviewProposal:
    """Compare against server-loaded run/assignment; preserve disagreements as proposals."""
    if assignment.binding != binding or assignment.reviewer_id != reviewer_id:
        raise ValueError("reviewer is not assigned to this exact run revision")
    if payload.get("binding") != asdict(binding):
        raise ValueError("stale or cross-tenant review binding")
    if payload.get("lane") != assignment.lane:
        raise ValueError("review lane differs from assignment")
    if payload.get("target_layer") not in LANE_TARGETS[assignment.lane]:
        raise ValueError("target layer belongs to a different review lane")
    if payload.get("kind") not in REVIEW_KINDS:
        raise ValueError("unknown review kind")
    review_id = require_text(payload.get("review_id"), "review id")
    rationale = require_text(payload.get("rationale"), "review rationale")
    references = payload.get("evidence_refs")
    if not isinstance(references, list) or not references or len(references) > 64:
        raise ValueError("bounded exact evidence references required")
    for reference in references:
        require_text(reference, "evidence reference")
    # Whitelist fields so an imported approval/training flag cannot acquire authority.
    body = {
        "binding": asdict(binding),
        "review_id": review_id,
        "lane": assignment.lane,
        "reviewer_id": reviewer_id,
        "assignment_ref": assignment.assignment_ref,
        "kind": payload["kind"],
        "target_layer": payload["target_layer"],
        "rationale": rationale,
        "evidence_refs": list(dict.fromkeys(references)),
        "status": "proposal_pending_adjudication",
        "training_label": False,
        "automatic_retraining": False,
    }
    if payload["kind"] in {"correction", "reject"}:
        for field in ("actual", "expected", "reproduction_steps"):
            body[field] = require_text(payload.get(field), field)
    if payload.get("supersedes_review_id") is not None:
        old_id = require_text(payload["supersedes_review_id"], "superseded review id")
        if old_id == review_id:
            raise ValueError("review cannot supersede itself")
        body["supersedes_review_id"] = old_id
    encoded = canonical(body)
    if len(encoded) > 20_000:
        raise ValueError("review proposal exceeds byte budget")
    return ReviewProposal(encoded.decode())


@dataclass(frozen=True)
class ReviewCursor:
    tenant_id: str
    feed_id: str
    sequence: int = 0
    event_hash: str = "0" * 64

    def __post_init__(self) -> None:
        require_text(self.tenant_id, "cursor tenant")
        require_text(self.feed_id, "cursor feed")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("invalid review cursor")
        require_sha256(self.event_hash, "cursor event hash")
        if self.sequence == 0 and self.event_hash != "0" * 64:
            raise ValueError("initial cursor must have empty chain")


def review_event(proposal: ReviewProposal, cursor: ReviewCursor, sequence: int) -> dict[str, Any]:
    """Build an event under the database's per-feed append lock; sequence gaps are allowed."""
    if type(sequence) is not int or sequence <= cursor.sequence:
        raise ValueError("review sequence must be strictly after recorded cursor")
    body = proposal.as_dict()
    if body["binding"]["tenant_id"] != cursor.tenant_id:
        raise ValueError("cross-tenant review event")
    envelope = {
        "tenant_id": cursor.tenant_id,
        "feed_id": cursor.feed_id,
        "sequence": sequence,
        "previous_hash": cursor.event_hash,
        "proposal_hash": proposal.proposal_hash,
    }
    return {**envelope, "event_hash": content_hash(envelope), "proposal": body}


def import_review_runs(
    cursor: ReviewCursor,
    events: list[dict[str, Any]],
    *,
    bindings: dict[str, RunBinding],
    assignments: dict[str, ReviewAssignment],
    existing_reviews: dict[str, str] | None = None,
) -> tuple[ReviewCursor, tuple[ReviewProposal, ...]]:
    """Validate the entire batch before returning a new cursor; caller commits atomically.

    ``bindings`` contains exact immutable historical runs, not an untrusted remote run list.
    The chain detects mutation/order gaps; authenticated transport and ACL are still required.
    """
    next_cursor = cursor
    imported: list[ReviewProposal] = []
    known = dict(existing_reviews or {})
    for event in events:
        if event.get("tenant_id") != cursor.tenant_id or event.get("feed_id") != cursor.feed_id:
            raise ValueError("wrong review feed")
        sequence = event.get("sequence")
        if type(sequence) is not int or sequence <= next_cursor.sequence:
            raise ValueError("review import must be strictly after recorded cursor in order")
        body = event.get("proposal")
        if not isinstance(body, dict) or not isinstance(body.get("binding"), dict):
            raise ValueError("invalid imported review proposal")
        binding = bindings.get(require_text(body["binding"].get("run_id"), "run id"))
        assignment = assignments.get(require_text(body.get("assignment_ref"), "assignment ref"))
        if binding is None or assignment is None:
            raise ValueError("unknown run or assignment")
        proposal = validate_review_proposal(
            body,
            binding=binding,
            assignment=assignment,
            reviewer_id=require_text(body.get("reviewer_id"), "reviewer id"),
        )
        if proposal.as_dict() != body:
            raise ValueError("imported review differs from canonical proposal")
        expected = review_event(proposal, next_cursor, sequence)
        if expected != event:
            raise ValueError("review chain or content hash mismatch")
        key = body["review_id"]
        if key in known:
            if known[key] != proposal.proposal_hash:
                raise ValueError("immutable review id conflict")
        else:
            imported.append(proposal)
            known[key] = proposal.proposal_hash
        next_cursor = ReviewCursor(cursor.tenant_id, cursor.feed_id, sequence, event["event_hash"])
    return next_cursor, tuple(imported)


def reproduction_fixture(
    proposal: ReviewProposal,
    *,
    fixture_id: str,
    input_sha256: str,
    acceptance_checks: list[str],
    permission_ref: str,
    split: str,
) -> dict[str, Any]:
    """Produce a fixture manifest, not a gold label or permission to reuse operational data."""
    body = proposal.as_dict()
    if body["kind"] not in {"correction", "reject"}:
        raise ValueError("reproduction requires a correction or rejection proposal")
    if split not in {"development", "calibration"}:
        raise ValueError("holdout is sealed from correction development")
    require_text(fixture_id, "fixture id")
    require_sha256(input_sha256, "fixture input sha256")
    require_text(permission_ref, "specific fixture-use permission reference")
    if not acceptance_checks:
        raise ValueError("targeted acceptance checks required")
    for check in acceptance_checks:
        require_text(check, "acceptance check")
    fixture = {
        "fixture_id": fixture_id,
        "input_sha256": input_sha256,
        "split": split,
        "permission_ref": permission_ref,
        "review_hash": proposal.proposal_hash,
        "binding": body["binding"],
        "target_layer": body["target_layer"],
        "actual": body["actual"],
        "expected": body["expected"],
        "reproduction_steps": body["reproduction_steps"],
        "acceptance_checks": list(dict.fromkeys(acceptance_checks)),
        "status": "proposal_fixture_not_gold",
        "automatic_retraining": False,
    }
    return {**fixture, "fixture_sha256": content_hash(fixture)}


def development_cases(
    manifest: list[dict[str, Any]], requested_ids: list[str]
) -> tuple[dict[str, Any], ...]:
    """Metadata-only partition check. Holdout bytes and labels never enter this function."""
    by_id: dict[str, dict[str, Any]] = {}
    source_splits: dict[str, str] = {}
    participant_splits: dict[str, str] = {}
    for case in manifest:
        allowed = {
            "case_id",
            "source_sha256",
            "participant_partition_sha256",
            "split",
            "permission_ref",
            "manifest_revision",
        }
        if set(case) != allowed:
            raise ValueError("manifest must contain metadata only; holdout content is sealed")
        cid = require_text(case["case_id"], "case id")
        require_text(case["permission_ref"], "dataset-use permission reference")
        require_text(case["manifest_revision"], "manifest revision")
        split = case["split"]
        if split not in {"development", "calibration", "holdout"} or cid in by_id:
            raise ValueError("duplicate case or invalid dataset split")
        for field, seen in (
            ("source_sha256", source_splits),
            ("participant_partition_sha256", participant_splits),
        ):
            fingerprint = require_sha256(case[field], field)
            if fingerprint in seen and seen[fingerprint] != split:
                raise ValueError("recording or participant leaks across dataset partitions")
            seen[fingerprint] = split
        by_id[cid] = case
    if len(set(requested_ids)) != len(requested_ids):
        raise ValueError("duplicate requested case")
    selected = []
    for cid in requested_ids:
        if cid not in by_id or by_id[cid]["split"] == "holdout":
            raise ValueError("unknown case or sealed holdout requested for development")
        selected.append(dict(by_id[cid]))
    return tuple(selected)


REQUIRED_GATE_AREAS = frozenset(
    {
        "regression",
        "development",
        "calibration",
        "sealed_holdout",
        "evidence_grounding",
        "slice_safety",
        "cost",
        "latency",
        "rollback",
    }
)


def evaluate_promotion(
    candidate: dict[str, Any],
    gate: dict[str, Any],
    checks: list[dict[str, Any]],
    approval: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fail closed, using server-loaded frozen gate and authenticated approval evidence.

    Thresholds are supplied by the approved gate; this kernel does not invent quality floors.
    Receipt validation is not test execution, publication, or a scientific validity claim.
    """
    candidate_revision = require_text(candidate.get("revision"), "candidate revision")
    artifact = require_sha256(candidate.get("artifact_sha256"), "candidate artifact")
    gate_revision = require_text(gate.get("revision"), "gate revision")
    require_text(gate.get("approval_ref"), "frozen gate approval reference")
    required = gate.get("required_checks")
    if not isinstance(required, list) or not required or len(required) != len(set(required)):
        raise ValueError("explicit unique frozen acceptance checks required")
    if not set(required) >= REQUIRED_GATE_AREAS:
        raise ValueError("frozen gate omits required evidence areas")
    gate_hash = content_hash(gate)
    reasons: list[str] = []
    if candidate.get("frozen_gate_sha256") != gate_hash:
        reasons.append("candidate_does_not_match_frozen_gate")
    if type(candidate.get("severe_unsupported_count")) is not int:
        reasons.append("missing_severe_error_count")
    elif candidate["severe_unsupported_count"] != 0:
        reasons.append("unresolved_severe_unsupported_allegations")
    if candidate.get("holdout_sealed") is not True:
        reasons.append("holdout_seal_not_attested")
    by_name: dict[str, dict[str, Any]] = {}
    for check in checks:
        name = require_text(check.get("name"), "check name")
        if name in by_name:
            raise ValueError("duplicate check receipt")
        by_name[name] = check
    for name in required:
        receipt = by_name.get(name)
        if receipt is None:
            reasons.append(f"missing_check:{name}")
            continue
        if receipt.get("candidate_sha256") != artifact or receipt.get("gate_sha256") != gate_hash:
            reasons.append(f"stale_check:{name}")
        if receipt.get("state") != "passed":
            reasons.append(f"not_passing:{name}")
        if not isinstance(receipt.get("receipt_ref"), str) or not receipt["receipt_ref"].strip():
            reasons.append(f"missing_receipt:{name}")
    receipt_body = {
        "candidate_revision": candidate_revision,
        "artifact_sha256": artifact,
        "gate_revision": gate_revision,
        "gate_sha256": gate_hash,
        "check_receipts_sha256": content_hash(checks),
    }
    if approval is None:
        reasons.append("explicit_candidate_promotion_approval_required")
    else:
        if any(approval.get(key) != value for key, value in receipt_body.items()):
            reasons.append("approval_does_not_bind_exact_candidate_gate_and_receipts")
        for field in ("approver_id", "approval_ref", "reason", "rollback_ref"):
            if not isinstance(approval.get(field), str) or not approval[field].strip():
                reasons.append(f"missing_approval:{field}")
    result = {
        **receipt_body,
        "state": "eligible_for_explicit_promotion" if not reasons else "blocked",
        "blockers": reasons,
        "numeric_publication": "withheld",
        "automatic_retraining": False,
        "production_mutated": False,
        "approval_ref": approval.get("approval_ref") if approval else None,
    }
    return {**result, "receipt_sha256": content_hash(result)}
