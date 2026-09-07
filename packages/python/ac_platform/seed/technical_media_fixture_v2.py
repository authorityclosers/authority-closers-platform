"""Package-owned two-film technical catalog revision; never Dipak instruction.

The v1 fixture and its strict external loader remain unchanged. This revision
uses the same technical catalog identity and is published as a new immutable
version by StagingSeedApplication, preserving older enrollments and history.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from ac_platform.catalog.content import (
    CanonicalActivityContent,
    CanonicalModuleContent,
    canonical_catalog_content_digest,
)
from ac_platform.seed.application import _stable_id
from ac_platform.seed.contract import (
    TECHNICAL_VALIDATION_SEED_KEY,
    TECHNICAL_VALIDATION_SLUG,
    TECHNICAL_VALIDATION_TITLE,
    SeedActivity,
    SeedModule,
    TechnicalValidationSeed,
)

FILM_FIXTURE_IDS = ("bbb-4k-30-normal", "caminandes-gran-dillama-1080p")
FILM_ACTIVITY_TITLES = (
    "STAGING TEST ONLY: Big Buck Bunny — licensed 12-second 4K clip",
    "STAGING TEST ONLY: Caminandes 2 — licensed 12-second 1080p clip",
)
FILM_ACTIVITY_PROMPTS = (
    "STAGING TEST ONLY — 12-second technical playback excerpt, not Dipak instruction. "
    "Big Buck Bunny, Sunflower version. Credits: Blender Foundation (2008), "
    "Janus Bager Kristensen (2013). License: Creative Commons Attribution 3.0 "
    "https://creativecommons.org/licenses/by/3.0/ . Official source: "
    "https://peach.blender.org/about/ . This excerpt was transcoded into a quality ladder "
    "and remuxed to MP4; captions are synthetic player-test cues, not film dialogue.",
    "STAGING TEST ONLY — 12-second technical playback excerpt, not Dipak instruction. "
    "Caminandes 2: Gran Dillama (2013), directed by Pablo Vazquez. Credits: Blender "
    "Foundation / Blender Studio. License: Creative Commons Attribution 4.0 "
    "https://creativecommons.org/licenses/by/4.0/ . Official source: "
    "https://studio.blender.org/projects/caminandes-2/ . This excerpt was transcoded into "
    "a quality ladder and remuxed to MP4; captions are synthetic player-test cues, "
    "not film dialogue.",
)
TECHNICAL_MEDIA_SOURCE_REF = "package:ac_platform.seed.technical_media_fixture_v2"


def technical_media_seed(release_id: str) -> TechnicalValidationSeed:
    if re.fullmatch(r"[0-9a-f]{40}", release_id) is None:
        raise ValueError("technical media seed requires a full release SHA")
    modules = (
        SeedModule(
            1,
            "STAGING TEST ONLY: Open-film player validation",
            (
                SeedActivity(1, "VIDEO", FILM_ACTIVITY_TITLES[0], True, FILM_ACTIVITY_PROMPTS[0]),
                SeedActivity(2, "VIDEO", FILM_ACTIVITY_TITLES[1], True, FILM_ACTIVITY_PROMPTS[1]),
                SeedActivity(3, "REFLECTION", "STAGING TEST ONLY: reflection plumbing", True),
                SeedActivity(
                    4, "IMPLEMENTATION_CHALLENGE", "STAGING TEST ONLY: challenge plumbing", True
                ),
            ),
            (),
        ),
        SeedModule(
            2,
            "STAGING TEST ONLY: Review workflow validation",
            (
                SeedActivity(1, "REVIEW", "STAGING TEST ONLY: review plumbing", True),
                SeedActivity(2, "IMPROVE", "STAGING TEST ONLY: improvement plumbing", True),
            ),
            (1,),
        ),
    )
    digest = canonical_catalog_content_digest(
        program_slug=TECHNICAL_VALIDATION_SLUG,
        program_title=TECHNICAL_VALIDATION_TITLE,
        modules=tuple(
            CanonicalModuleContent(
                position=module.position,
                title=module.title,
                prerequisite_positions=module.prerequisite_positions,
                activities=tuple(
                    CanonicalActivityContent(
                        position=activity.position,
                        kind=activity.kind,
                        title=activity.title,
                        is_required=activity.is_required,
                        prompt=activity.prompt,
                    )
                    for activity in module.activities
                ),
            )
            for module in modules
        ),
    )
    return TechnicalValidationSeed(
        seed_key=TECHNICAL_VALIDATION_SEED_KEY,
        contract_version="staging-technical-media-seed.v2",
        slug=TECHNICAL_VALIDATION_SLUG,
        title=TECHNICAL_VALIDATION_TITLE,
        source_ref=TECHNICAL_MEDIA_SOURCE_REF,
        review_status="technical-validation",
        reviewed_by="user-authorized-alpha-public-film-fixtures",
        reviewed_at=datetime(2026, 9, 7, tzinfo=UTC),
        release_id=release_id,
        modules=modules,
        content_digest=digest,
        seed_kind="technical-validation",
    )


def technical_media_identity(release_id: str) -> tuple[UUID, UUID, UUID, tuple[UUID, UUID]]:
    seed = technical_media_seed(release_id)
    return (
        _stable_id("program", seed.seed_key),
        _stable_id("version", seed.content_digest),
        _stable_id("module", f"{seed.content_digest}:1"),
        (
            _stable_id("activity", f"{seed.content_digest}:1:1"),
            _stable_id("activity", f"{seed.content_digest}:1:2"),
        ),
    )


__all__ = ["technical_media_seed", "technical_media_identity"]
