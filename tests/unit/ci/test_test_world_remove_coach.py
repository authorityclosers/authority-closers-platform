"""Taking the coach out of the test world's TEST workspaces (orchestrator, 15 Nov 2026, on the
owner's approval: no real colleague in a TEST workspace). The script finds the workspaces only by
the build's own command ids, refuses anything it was not asked to touch, and shows emails masked."""

import importlib.util
import json
import sys
from pathlib import Path
from uuid import UUID, uuid5

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "scripts/data-changes/test-world-remove-coach.py"


def _load(name: str, path: str):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, ROOT / path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


remove = _load("test_world_remove_coach", SCRIPT)


def _raw(**overrides: object) -> str:
    body: dict[str, object] = {
        "command_id": "8b0d0c2e-7f43-4e47-9d8e-3f8f3c1b5a10",
        "build_command_id": "0b8d1c5c-e213-42a6-ac39-c37d99c7cea4",
        "approver_email": "owner@example.test",
        "coach_email": "coach@example.test",
        "issue": "orchestrator 15 Nov 2026 (Pulse 54265ec8)",
    }
    body.update(overrides)
    return json.dumps({key: value for key, value in body.items() if value is not None})


def _refusal(raised: pytest.ExceptionInfo[SystemExit]) -> dict[str, object]:
    return dict(json.loads(str(raised.value.code)))


def test_it_defaults_to_the_three_test_workspaces() -> None:
    spec = remove.spec_of(_raw())
    assert spec["organisations"] == ["sahyadri", "suryoday", "kavach"]


def test_it_reads_a_file_as_well_as_json_text(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_text(_raw(organisations=["kavach"]), encoding="utf-8")
    assert remove.spec_of(str(path))["organisations"] == ["kavach"]


@pytest.mark.parametrize(
    "field", ["command_id", "build_command_id", "approver_email", "coach_email", "issue"]
)
def test_it_refuses_missing_input(field: str) -> None:
    with pytest.raises(SystemExit) as raised:
        remove.spec_of(_raw(**{field: None}))
    assert _refusal(raised) == {"refused": "missing_input", "fields": [field]}


def test_it_refuses_an_organisation_outside_the_test_world() -> None:
    with pytest.raises(SystemExit) as raised:
        remove.spec_of(_raw(organisations=["sahyadri", "ac-sales-sandbox"]))
    assert _refusal(raised)["refused"] == "unknown_organisation"


def test_it_never_removes_the_approver() -> None:
    with pytest.raises(SystemExit) as raised:
        remove.spec_of(_raw(coach_email=" Owner@Example.test "))
    assert _refusal(raised) == {"refused": "coach_is_the_approver"}


def test_a_bad_command_id_is_refused() -> None:
    with pytest.raises(ValueError):
        remove.spec_of(_raw(build_command_id="not-a-uuid"))


def test_it_finds_the_workspaces_by_the_generators_own_command_ids() -> None:
    build = UUID("0b8d1c5c-e213-42a6-ac39-c37d99c7cea4")
    assert remove.organisation_command(build, "kavach") == uuid5(build, "organisation:kavach")
    generator = (ROOT / "scripts/data-changes/sandbox-organisations.py").read_text("utf-8")
    assert 'command_id = uuid5(base, f"organisation:{key}")' in generator
    assert "Organisation.creation_command_id == command_id" in generator


def test_emails_are_masked() -> None:
    assert remove.mask("coach@example.test") == "c***@example.test"
    assert remove.mask(None) == "[none]"
    assert remove.mask("no-at-sign") == "[none]"


def test_it_works_through_the_apps_own_member_removal() -> None:
    source = (ROOT / SCRIPT).read_text("utf-8")
    assert "service.remove_member(" in source
    assert "operator_reference=" in source
    assert "append_audit_event(" in source
    assert 'mode == "apply"' in source and "await db.rollback()" in source
