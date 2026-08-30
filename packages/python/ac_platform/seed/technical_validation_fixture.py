"""Synthetic STAGING-ONLY catalog data for exercising the API seam.

This is deliberately not an approved Free Course payload.  It has a separate
contract identity, stable placeholder copy, and can only be selected through
the explicit technical-validation CLI acknowledgement.
"""

from __future__ import annotations

from ac_platform.seed.contract import TechnicalValidationSeed

TECHNICAL_VALIDATION_FIXTURE: dict[str, object] = {
    "contract_version": "staging-technical-validation-seed.v1",
    "seed_key": "staging-technical-validation",
    "program": {
        "slug": "staging-technical-validation",
        "title": "STAGING-ONLY Technical Validation Catalog",
    },
    "content": {
        "source_ref": "package:ac_platform.seed.technical_validation_fixture",
        "review_status": "technical-validation",
        "reviewed_by": "technical-validation-fixture",
        "reviewed_at": "2026-08-30T00:00:00Z",
        "release_id": "$AC_RELEASE_ID",
    },
    "modules": [
        {
            "position": 1,
            "title": "STAGING-ONLY validation module one",
            "activities": [
                {
                    "position": 1,
                    "kind": "VIDEO",
                    "title": "Technical validation video",
                    "prompt": None,
                    "is_required": True,
                },
                {
                    "position": 2,
                    "kind": "REFLECTION",
                    "title": "Technical validation reflection",
                    "prompt": None,
                    "is_required": True,
                },
                {
                    "position": 3,
                    "kind": "IMPLEMENTATION_CHALLENGE",
                    "title": "Technical validation challenge",
                    "prompt": None,
                    "is_required": True,
                },
            ],
            "prerequisite_positions": [],
        },
        {
            "position": 2,
            "title": "STAGING-ONLY validation module two",
            "activities": [
                {
                    "position": 1,
                    "kind": "REVIEW",
                    "title": "Technical validation review",
                    "prompt": None,
                    "is_required": True,
                },
                {
                    "position": 2,
                    "kind": "IMPROVE",
                    "title": "Technical validation improvement",
                    "prompt": None,
                    "is_required": True,
                },
            ],
            "prerequisite_positions": [1],
        },
    ],
}


def technical_validation_seed(release_id: str) -> TechnicalValidationSeed:
    """Build the explicit technical fixture bound to the running release."""

    return TechnicalValidationSeed.from_mapping(
        TECHNICAL_VALIDATION_FIXTURE,
        environment="staging",
        expected_release_id=release_id,
        _technical_validation=True,
    )


__all__ = ["TECHNICAL_VALIDATION_FIXTURE", "technical_validation_seed"]
