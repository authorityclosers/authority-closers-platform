from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ac_platform.practice.activation import PracticeActivationError, prepare_receipt

ROOT = Path(__file__).parents[2]
CATALOG = ROOT / "packages/python/ac_platform/practice/exercise-library.draft.json"
POLICY = ROOT / "packages/python/ac_platform/practice/daily-selection-policy.v1.json"


def test_current_editorial_draft_is_refused_until_review(tmp_path: Path) -> None:
    with pytest.raises(PracticeActivationError, match="questionbank is not published"):
        prepare_receipt(
            catalog_path=CATALOG,
            policy_path=POLICY,
            output_path=tmp_path / "receipt.json",
            environment="staging",
            tenant_id=uuid4(),
        )


def test_approved_bundle_receipt_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    catalog = {
        "status": "published",
        "sets": [
            {
                "id": "india-daily-english",
                "review_status": "approved",
                "competition_eligible": False,
                "assessment_eligible": False,
            }
        ],
    }
    policy = {
        "status": "approved",
        "languages": [
            {
                "id": "english",
                "label": "English",
                "set_id": "india-daily-english",
            }
        ],
    }
    catalog_path = tmp_path / "catalog.json"
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "release" / "receipt.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    tenant_id = UUID("11111111-1111-4111-8111-111111111111")

    first = prepare_receipt(
        catalog_path=catalog_path,
        policy_path=policy_path,
        output_path=output_path,
        environment="staging",
        tenant_id=tenant_id,
    )
    second = prepare_receipt(
        catalog_path=catalog_path,
        policy_path=policy_path,
        output_path=output_path,
        environment="staging",
        tenant_id=tenant_id,
    )

    assert first["receipt_status"] == "prepared"
    assert second["receipt_status"] == "already_prepared"
    assert first["questionbank_digest"] == second["questionbank_digest"]
    assert json.loads(output_path.read_text("utf-8"))["database_mutated"] is False
