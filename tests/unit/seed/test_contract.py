from __future__ import annotations

import json
from pathlib import Path

import pytest

from ac_platform.seed.contract import (
    SeedContractError,
    load_seed,
    load_technical_validation_seed,
)
from ac_platform.seed.technical_validation_fixture import (
    TECHNICAL_VALIDATION_FIXTURE,
    technical_validation_seed,
)

FIXTURE = Path(__file__).parents[2] / "fixtures" / "free_course_staging_test_fixture.json"
TEST_RELEASE = "0000000000000000000000000000000000000000"


def test_test_fixture_is_explicit_and_digest_is_deterministic() -> None:
    first = load_seed(FIXTURE, environment="test", expected_release_id=TEST_RELEASE)
    second = load_seed(FIXTURE, environment="test", expected_release_id=TEST_RELEASE)

    assert first.content_digest == second.content_digest
    assert len(first.modules) == 4
    assert sum(len(module.activities) for module in first.modules) == 5
    assert all(activity.prompt for module in first.modules for activity in module.activities)


def test_reviewed_seed_requires_explicit_bounded_activity_prompt(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del payload["modules"][0]["activities"][0]["prompt"]
    missing_path = tmp_path / "missing-prompt.json"
    missing_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SeedContractError, match="missing required keys: prompt"):
        load_seed(missing_path, environment="test", expected_release_id=TEST_RELEASE)

    payload["modules"][0]["activities"][0]["prompt"] = " "
    blank_path = tmp_path / "blank-prompt.json"
    blank_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SeedContractError, match="prompt must be non-blank"):
        load_seed(blank_path, environment="test", expected_release_id=TEST_RELEASE)

    payload["modules"][0]["activities"][0]["prompt"] = "x" * 2001
    long_path = tmp_path / "long-prompt.json"
    long_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SeedContractError, match="prompt must be non-blank and at most 2000"):
        load_seed(long_path, environment="test", expected_release_id=TEST_RELEASE)


def test_staging_rejects_test_fixture_status() -> None:
    with pytest.raises(SeedContractError, match="review_status must be reviewed"):
        load_seed(FIXTURE, environment="staging", expected_release_id=TEST_RELEASE)


def test_missing_seed_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SeedContractError, match="explicit reviewed seed data file is required"):
        load_seed(tmp_path / "missing.json", environment="staging", expected_release_id="a" * 40)


def test_mutating_content_changes_digest_without_falling_back_to_defaults(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["modules"][0]["title"] = "Mutated fixture module"
    path = tmp_path / "mutated.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    original = load_seed(FIXTURE, environment="test", expected_release_id=TEST_RELEASE)
    mutated = load_seed(path, environment="test", expected_release_id=TEST_RELEASE)
    assert mutated.content_digest != original.content_digest

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["modules"][0]["activities"][0]["prompt"] = "A changed reviewed prompt."
    prompt_path = tmp_path / "mutated-prompt.json"
    prompt_path.write_text(json.dumps(payload), encoding="utf-8")
    prompt_mutated = load_seed(
        prompt_path,
        environment="test",
        expected_release_id=TEST_RELEASE,
    )
    assert prompt_mutated.content_digest != original.content_digest


@pytest.mark.parametrize(
    "object_level",
    ["root", "program", "content", "module", "activity"],
)
def test_seed_objects_reject_unknown_keys(tmp_path: Path, object_level: str) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    target = {
        "root": payload,
        "program": payload["program"],
        "content": payload["content"],
        "module": payload["modules"][0],
        "activity": payload["modules"][0]["activities"][0],
    }[object_level]
    target["unexpected"] = True
    path = tmp_path / f"unknown-{object_level}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SeedContractError, match="contains unknown keys: unexpected"):
        load_seed(path, environment="test", expected_release_id=TEST_RELEASE)


@pytest.mark.parametrize(
    ("object_level", "required_key"),
    [
        ("root", "seed_key"),
        ("program", "slug"),
        ("content", "source_ref"),
        ("module", "title"),
        ("activity", "prompt"),
    ],
)
def test_seed_objects_reject_missing_required_keys(
    tmp_path: Path,
    object_level: str,
    required_key: str,
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    target = {
        "root": payload,
        "program": payload["program"],
        "content": payload["content"],
        "module": payload["modules"][0],
        "activity": payload["modules"][0]["activities"][0],
    }[object_level]
    del target[required_key]
    path = tmp_path / f"missing-{object_level}-{required_key}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        SeedContractError,
        match=rf"missing required keys: {required_key}",
    ):
        load_seed(path, environment="test", expected_release_id=TEST_RELEASE)


@pytest.mark.parametrize(
    ("object_level", "snippet"),
    [
        ("root", '"seed_key": "free-course"'),
        ("program", '"slug": "free-course-seed-fixture"'),
        (
            "content",
            '"source_ref": "tests/fixtures/free_course_staging_test_fixture.json"',
        ),
        ("module", '"title": "Fixture module one"'),
        ("activity", '"kind": "VIDEO"'),
    ],
)
def test_seed_json_rejects_duplicate_keys_at_every_object_level(
    tmp_path: Path,
    object_level: str,
    snippet: str,
) -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    duplicate = source.replace(snippet, f"{snippet}, {snippet}", 1)
    assert duplicate != source
    path = tmp_path / f"duplicate-{object_level}.json"
    path.write_text(duplicate, encoding="utf-8")

    with pytest.raises(SeedContractError, match="duplicate JSON key is not allowed"):
        load_seed(path, environment="test", expected_release_id=TEST_RELEASE)


def test_technical_fixture_uses_a_separate_identity_and_loader(tmp_path: Path) -> None:
    release_id = "0123456789abcdef0123456789abcdef01234567"
    path = tmp_path / "technical-validation.json"
    path.write_text(json.dumps(TECHNICAL_VALIDATION_FIXTURE), encoding="utf-8")

    technical = load_technical_validation_seed(
        path,
        environment="staging",
        expected_release_id=release_id,
    )
    assert technical.seed_kind == "technical-validation"
    assert technical.slug == "staging-technical-validation"
    assert technical.title == "STAGING-ONLY Technical Validation Catalog"
    assert technical.release_id == release_id
    assert all(
        activity.prompt is None for module in technical.modules for activity in module.activities
    )
    assert technical_validation_seed(release_id).content_digest == technical.content_digest

    technical_payload = json.loads(json.dumps(TECHNICAL_VALIDATION_FIXTURE))
    technical_payload["modules"][0]["activities"][0]["prompt"] = "Invented content"
    authored_path = tmp_path / "technical-with-prompt.json"
    authored_path.write_text(json.dumps(technical_payload), encoding="utf-8")
    with pytest.raises(SeedContractError, match="explicit null"):
        load_technical_validation_seed(
            authored_path,
            environment="staging",
            expected_release_id=release_id,
        )

    with pytest.raises(SeedContractError, match="contract_version must be"):
        load_seed(path, environment="staging", expected_release_id=release_id)
