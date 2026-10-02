"""Release packaging stays on main and all published images carry their revision."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/application.yml").read_text())
PACKAGING_JOB = WORKFLOW["jobs"]["package-release-images"]


def _matches(node: ast.expr) -> bool:
    """Interpret only boolean operators and literal equality in the job guard."""
    if isinstance(node, ast.BoolOp):
        values = [_matches(value) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
    if isinstance(node, ast.Compare):
        assert len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
        return ast.literal_eval(node.left) == ast.literal_eval(node.comparators[0])
    raise AssertionError(f"Unsupported guard expression: {ast.dump(node)}")


@pytest.mark.parametrize(
    "ref",
    ["refs/heads/main", "refs/heads/task/platform/830", "refs/pull/193/merge", "refs/tags/v1"],
)
@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "pull_request", "schedule"])
def test_packaging_and_bundle_reclamation_are_main_only(ref: str, event: str) -> None:
    guard = (
        PACKAGING_JOB["if"]
        .replace("github.ref", repr(ref))
        .replace("github.event_name", repr(event))
        .replace("&&", " and ")
        .replace("||", " or ")
    )
    qualifies = _matches(ast.parse(guard, mode="eval").body)
    assert qualifies is (ref == "refs/heads/main" and event in {"push", "workflow_dispatch"})
    names = {step.get("name") for step in PACKAGING_JOB["steps"]}
    assert "Upload reviewed release bundle" in names
    assert "Reclaim superseded release artifacts after verified upload" in names


@pytest.mark.parametrize(
    ("dockerfile", "target"),
    [
        ("Dockerfile.python", "runtime"),
        ("Dockerfile.web", "learner"),
        ("Dockerfile.web", "admin"),
        ("Dockerfile.web", "coach"),
    ],
)
def test_release_runtime_stages_label_the_supplied_revision(dockerfile: str, target: str) -> None:
    source = (ROOT / "infra/application" / dockerfile).read_text()
    stages = re.split(r"(?m)^FROM ", source)[1:]
    stage = next(stage for stage in stages if stage.splitlines()[0].endswith(f" AS {target}"))
    assert re.search(r"(?m)^ARG AC_RELEASE_ID$", stage)
    assert re.search(r"(?m)^LABEL org\.opencontainers\.image\.revision=\$\{AC_RELEASE_ID\}$", stage)
    assert stage.index("ARG AC_RELEASE_ID") < stage.index("LABEL org.opencontainers.image.revision")
