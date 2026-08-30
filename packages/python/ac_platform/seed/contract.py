"""Fail-closed contract for the reviewed Free Course staging seed.

There is intentionally no default course payload in application code.  The
static learner preview is not an authoritative source and cannot be promoted
by this loader.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self, cast

from ac_platform.catalog.content import (
    CanonicalActivityContent,
    CanonicalModuleContent,
    canonical_catalog_content_digest,
)
from ac_platform.catalog.models import ACTIVITY_PROMPT_MAX_LENGTH, ActivityKind

SEED_CONTRACT_VERSION = "free-course-staging-seed.v1"
SEED_KEY = "free-course"
TECHNICAL_VALIDATION_CONTRACT_VERSION = "staging-technical-validation-seed.v1"
TECHNICAL_VALIDATION_SEED_KEY = "staging-technical-validation"
TECHNICAL_VALIDATION_SLUG = "staging-technical-validation"
TECHNICAL_VALIDATION_TITLE = "STAGING-ONLY Technical Validation Catalog"
EXPECTED_MODULE_COUNT = 4
TECHNICAL_VALIDATION_MODULE_COUNT = 2
EXPECTED_ACTIVITY_COUNT = 5
REQUIRED_ACTIVITY_KINDS = frozenset(kind.value for kind in ActivityKind)
_RELEASE_ID = re.compile(r"^[0-9a-f]{40}$")


class SeedContractError(ValueError):
    """The supplied seed is missing reviewed, structurally valid content."""


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SeedContractError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _exact_mapping(
    value: object,
    field: str,
    required_keys: frozenset[str],
) -> Mapping[str, object]:
    result = _mapping(value, field)
    actual_keys = set(result)
    unknown = sorted(actual_keys - required_keys)
    missing = sorted(required_keys - actual_keys)
    if unknown:
        raise SeedContractError(f"{field} contains unknown keys: {', '.join(unknown)}")
    if missing:
        raise SeedContractError(f"{field} is missing required keys: {', '.join(missing)}")
    return result


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SeedContractError(f"duplicate JSON key is not allowed: {key}")
        result[key] = value
    return result


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise SeedContractError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise SeedContractError(f"{field} must be non-blank and at most {maximum} characters")
    return normalized


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SeedContractError(f"{field} must be a positive integer")
    return value


def _reviewed_at(value: object) -> datetime:
    raw = _text(value, "content.reviewed_at", 64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SeedContractError("content.reviewed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SeedContractError("content.reviewed_at must include a timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SeedActivity:
    position: int
    kind: str
    title: str
    is_required: bool
    prompt: str | None = None


@dataclass(frozen=True, slots=True)
class SeedModule:
    position: int
    title: str
    activities: tuple[SeedActivity, ...]
    prerequisite_positions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FreeCourseSeed:
    """A complete reviewed snapshot; content is never inferred."""

    seed_key: str
    contract_version: str
    slug: str
    title: str
    source_ref: str
    review_status: str
    reviewed_by: str
    reviewed_at: datetime
    release_id: str
    modules: tuple[SeedModule, ...]
    content_digest: str
    seed_kind: str

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, object],
        *,
        environment: str,
        expected_release_id: str,
        _technical_validation: bool = False,
    ) -> Self:
        raw = _exact_mapping(
            raw,
            "seed",
            frozenset({"contract_version", "seed_key", "program", "content", "modules"}),
        )
        contract_version = _text(raw.get("contract_version"), "contract_version", 80)
        required_contract_version = (
            TECHNICAL_VALIDATION_CONTRACT_VERSION
            if _technical_validation
            else SEED_CONTRACT_VERSION
        )
        if contract_version != required_contract_version:
            raise SeedContractError(f"contract_version must be {required_contract_version}")
        seed_key = _text(raw.get("seed_key"), "seed_key", 120)
        required_seed_key = TECHNICAL_VALIDATION_SEED_KEY if _technical_validation else SEED_KEY
        if seed_key != required_seed_key:
            raise SeedContractError(f"seed_key must be {required_seed_key}")

        program = _exact_mapping(
            raw.get("program"),
            "program",
            frozenset({"slug", "title"}),
        )
        slug = _text(program.get("slug"), "program.slug", 120)
        title = _text(program.get("title"), "program.title", 200)

        content = _exact_mapping(
            raw.get("content"),
            "content",
            frozenset({"source_ref", "review_status", "reviewed_by", "reviewed_at", "release_id"}),
        )
        source_ref = _text(content.get("source_ref"), "content.source_ref", 500)
        review_status = _text(content.get("review_status"), "content.review_status", 32)
        allowed_review_status = {"technical-validation"} if _technical_validation else {"reviewed"}
        if not _technical_validation and environment == "test":
            allowed_review_status.add("test-fixture")
        if review_status not in allowed_review_status:
            raise SeedContractError(
                "content.review_status must be reviewed"
                + (" (or test-fixture in test)" if environment == "test" else "")
            )
        reviewed_by = _text(content.get("reviewed_by"), "content.reviewed_by", 200)
        reviewed_at = _reviewed_at(content.get("reviewed_at"))
        release_id = _text(content.get("release_id"), "content.release_id", 128)
        if (
            environment in {"staging", "production"}
            and not _RELEASE_ID.fullmatch(release_id)
            and not (_technical_validation and release_id == "$AC_RELEASE_ID")
        ):
            raise SeedContractError("content.release_id must be a full lowercase Git SHA")
        if _technical_validation:
            if environment != "staging":
                raise SeedContractError("technical validation seed requires staging")
            if slug != TECHNICAL_VALIDATION_SLUG or title != TECHNICAL_VALIDATION_TITLE:
                raise SeedContractError(
                    "technical validation seed must use its STAGING-ONLY catalog identity"
                )
            if release_id == "$AC_RELEASE_ID":
                release_id = _text(expected_release_id, "expected_release_id", 128)
            if not _RELEASE_ID.fullmatch(release_id):
                raise SeedContractError("expected_release_id must be a full lowercase Git SHA")
        if release_id != expected_release_id:
            raise SeedContractError(
                "content.release_id must match the reviewed release being seeded"
            )

        raw_modules = raw.get("modules")
        if not isinstance(raw_modules, list):
            raise SeedContractError("modules must be an array")
        expected_module_count = (
            TECHNICAL_VALIDATION_MODULE_COUNT if _technical_validation else EXPECTED_MODULE_COUNT
        )
        if len(raw_modules) != expected_module_count:
            raise SeedContractError(
                f"the seed must contain exactly {expected_module_count} modules"
            )

        modules: list[SeedModule] = []
        for index, raw_module in enumerate(raw_modules, start=1):
            module_path = f"modules[{index - 1}]"
            module = _exact_mapping(
                raw_module,
                module_path,
                frozenset({"position", "title", "activities", "prerequisite_positions"}),
            )
            position = _positive_int(module.get("position"), f"modules[{index - 1}].position")
            if position != index:
                raise SeedContractError(
                    f"module positions must be exactly 1..{expected_module_count}"
                )
            module_title = _text(module.get("title"), f"modules[{index - 1}].title", 200)
            raw_activities = module.get("activities")
            if not isinstance(raw_activities, list):
                raise SeedContractError(f"modules[{index - 1}].activities must be an array")
            activities: list[SeedActivity] = []
            for activity_index, raw_activity in enumerate(raw_activities, start=1):
                activity_path = f"modules[{index - 1}].activities[{activity_index - 1}]"
                activity = _exact_mapping(
                    raw_activity,
                    activity_path,
                    frozenset({"position", "kind", "title", "prompt", "is_required"}),
                )
                activity_position = _positive_int(
                    activity.get("position"),
                    f"modules[{index - 1}].activities[{activity_index - 1}].position",
                )
                if activity_position != activity_index:
                    raise SeedContractError("activity positions must be contiguous per module")
                kind = _text(
                    activity.get("kind"),
                    f"modules[{index - 1}].activities[{activity_index - 1}].kind",
                    32,
                )
                if kind not in REQUIRED_ACTIVITY_KINDS:
                    raise SeedContractError(f"unsupported activity kind: {kind}")
                activity_title = _text(
                    activity.get("title"),
                    f"modules[{index - 1}].activities[{activity_index - 1}].title",
                    240,
                )
                raw_prompt = activity["prompt"]
                if _technical_validation:
                    if raw_prompt is not None:
                        raise SeedContractError(
                            "technical-validation activity.prompt must be explicit null; "
                            "the fixture is plumbing-only"
                        )
                    activity_prompt = None
                else:
                    activity_prompt = _text(
                        raw_prompt,
                        f"{activity_path}.prompt",
                        ACTIVITY_PROMPT_MAX_LENGTH,
                    )
                required = activity["is_required"]
                if not isinstance(required, bool):
                    raise SeedContractError("activity.is_required must be boolean")
                activities.append(
                    SeedActivity(
                        activity_position,
                        kind,
                        activity_title,
                        required,
                        activity_prompt,
                    )
                )
            if "prerequisite_positions" not in module:
                raise SeedContractError("module.prerequisite_positions must be explicit")
            raw_prerequisites = module["prerequisite_positions"]
            if not isinstance(raw_prerequisites, list):
                raise SeedContractError("module.prerequisite_positions must be an array")
            prerequisites = tuple(
                _positive_int(value, f"modules[{index - 1}].prerequisite_positions")
                for value in raw_prerequisites
            )
            if len(set(prerequisites)) != len(prerequisites):
                raise SeedContractError("module prerequisites must be unique")
            if any(value >= position for value in prerequisites):
                raise SeedContractError("module prerequisites must point to earlier modules")
            modules.append(SeedModule(position, module_title, tuple(activities), prerequisites))

        activity_kinds = {activity.kind for module in modules for activity in module.activities}
        activity_count = sum(len(module.activities) for module in modules)
        if activity_count != EXPECTED_ACTIVITY_COUNT or activity_kinds != REQUIRED_ACTIVITY_KINDS:
            raise SeedContractError(
                "the reviewed Free Course seed must contain exactly the five approved "
                "activity kinds"
            )

        digest = canonical_catalog_content_digest(
            program_slug=slug,
            program_title=title,
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
        return cls(
            seed_key,
            contract_version,
            slug,
            title,
            source_ref,
            review_status,
            reviewed_by,
            reviewed_at,
            release_id,
            tuple(modules),
            digest,
            "technical-validation" if _technical_validation else "reviewed",
        )


@dataclass(frozen=True, slots=True)
class TechnicalValidationSeed(FreeCourseSeed):
    """Synthetic staging-only content for exercising the functional seam."""


def load_seed(
    path: Path,
    *,
    environment: str,
    expected_release_id: str,
) -> FreeCourseSeed:
    """Read one explicit seed file; missing/invalid files fail closed."""

    return _load_seed_file(
        path,
        environment=environment,
        expected_release_id=expected_release_id,
        technical_validation=False,
    )


def load_technical_validation_seed(
    path: Path,
    *,
    environment: str,
    expected_release_id: str,
) -> TechnicalValidationSeed:
    """Read only the separately marked STAGING-ONLY technical fixture."""

    loaded = _load_seed_file(
        path,
        environment=environment,
        expected_release_id=expected_release_id,
        technical_validation=True,
    )
    if not isinstance(loaded, TechnicalValidationSeed):
        raise SeedContractError("technical validation fixture did not use its separate seed type")
    return loaded


def _load_seed_file(
    path: Path,
    *,
    environment: str,
    expected_release_id: str,
    technical_validation: bool,
) -> FreeCourseSeed:
    try:
        raw_value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except FileNotFoundError as exc:
        message = (
            "an explicit reviewed seed data file is required"
            if not technical_validation
            else "an explicit technical validation seed data file is required"
        )
        raise SeedContractError(message) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeedContractError("the seed data file is not valid UTF-8 JSON") from exc
    seed_class = TechnicalValidationSeed if technical_validation else FreeCourseSeed
    return seed_class.from_mapping(
        _mapping(raw_value, "seed"),
        environment=environment,
        expected_release_id=expected_release_id,
        _technical_validation=technical_validation,
    )


__all__ = [
    "EXPECTED_ACTIVITY_COUNT",
    "EXPECTED_MODULE_COUNT",
    "FreeCourseSeed",
    "REQUIRED_ACTIVITY_KINDS",
    "SEED_CONTRACT_VERSION",
    "SeedActivity",
    "SeedContractError",
    "SeedModule",
    "TECHNICAL_VALIDATION_CONTRACT_VERSION",
    "TECHNICAL_VALIDATION_MODULE_COUNT",
    "TECHNICAL_VALIDATION_SEED_KEY",
    "TECHNICAL_VALIDATION_SLUG",
    "TECHNICAL_VALIDATION_TITLE",
    "TechnicalValidationSeed",
    "load_seed",
    "load_technical_validation_seed",
]
