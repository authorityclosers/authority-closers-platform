"""Fictional path/evidence fixtures for the M1a merge rule."""

import builtins
import os
import socket
import sys
from pathlib import Path

import pytest

# Support both pytest's console entry point and python -m pytest in importlib mode.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci.merge_class import classify_changed_files  # noqa: E402

PROTECTED = [
    ("apps/nested/AGENTS.md", "protected:instructions"),
    ("docs/CLAUDE.md", "protected:instructions"),
    (".github/workflows/check.yml", "protected:automation"),
    ("infra/config.py", "protected:automation"),
    ("scripts/ci/check.py", "protected:automation"),
    ("scripts/ops/check.py", "protected:automation"),
    ("scripts/data-changes/production-membership.py", "protected:automation"),
    ("scripts/ac_task.py", "protected:automation"),
    ("apps/Dockerfile", "protected:deployment"),
    ("apps/Dockerfile.dev", "protected:deployment"),
    ("apps/Dockerfile-dev", "protected:deployment"),
    ("apps/Dockerfile_dev", "protected:deployment"),
    ("apps/api.Dockerfile", "protected:deployment"),
    ("apps/compose.yml", "protected:deployment"),
    ("apps/docker-compose.dev.yaml", "protected:deployment"),
    ("apps/.env", "protected:secrets"),
    ("apps/dev.env.example", "protected:secrets"),
    ("packages/secrets/config.json", "protected:secrets"),
    ("tools/.infisical.json", "protected:secrets"),
    ("db/migrations/0001_add.py", "protected:migration"),
    ("scripts/ci/merge_class.py", "protected:classifier"),
] + [
    (f"apps/{term}/config.py", f"protected:name:{term}")
    for term in (
        "payment",
        "billing",
        "price",
        "checkout",
        "subscription",
        "top-up",
        "credit",
        "entitlement",
        "consent",
        "retention",
        "deletion",
        "score",
        "purchase",
    )
]


def classify(path, status="modified", previous=None):
    record = {"filename": path, "status": status}
    if previous is not None:
        record["previous_filename"] = previous
    return classify_changed_files([record], {path: "fictional head"}, changed_files=1)


@pytest.mark.parametrize("path,reason", PROTECTED)
@pytest.mark.parametrize("case", [str, str.upper])
@pytest.mark.parametrize("direction", ["added", "modified", "removed", "rename-in", "rename-out"])
def test_protected_paths_both_rename_names_and_deletes(path, reason, case, direction):
    path = case(path)
    result = (
        classify(path, "renamed", "apps/ordinary.py")
        if direction == "rename-in"
        else classify("apps/ordinary.py", "renamed", path)
        if direction == "rename-out"
        else classify(path, direction)
    )
    assert result["class"] == "escalation"
    assert reason in result["reasons"]
    assert result["reasons"] == sorted(set(result["reasons"]))


@pytest.mark.parametrize("root", ["apps", "packages", "tests", "docs", "tools"])
@pytest.mark.parametrize("status", ["added", "modified", "removed", "renamed"])
def test_ordinary_roots(root, status):
    assert classify(
        f"{root}/ordinary.py", status, "apps/old.py" if status == "renamed" else None
    ) == {
        "class": "routine",
        "reasons": [],
    }


@pytest.mark.parametrize(
    "path", ["README.md", "new-root/file.py", "scripts/other.py", "db/model.py", "APPS/ordinary.py"]
)
def test_unknown_roots(path):
    assert classify(path) == {"class": "escalation", "reasons": ["path:unknown-root"]}


@pytest.mark.parametrize(
    "record,reason",
    [
        (None, "evidence:record"),
        ({}, "evidence:path"),
        ({"filename": "apps/file.py"}, "evidence:status"),
        ({"filename": "apps/file.py", "status": []}, "evidence:status"),
        ({"filename": "apps/file.py", "status": "copied"}, "evidence:status"),
        ({"filename": "apps/file.py", "status": "renamed"}, "evidence:rename"),
        (
            {"filename": "apps/file.py", "status": "renamed", "previous_filename": "apps/file.py"},
            "evidence:rename",
        ),
        (
            {"filename": "apps/file.py", "status": "modified", "previous_filename": "apps/old.py"},
            "evidence:rename",
        ),
    ],
)
def test_missing_malformed_or_ambiguous_records(record, reason):
    result = classify_changed_files([record], {"apps/file.py": ""}, changed_files=1)
    assert result["class"] == "escalation" and reason in result["reasons"]


@pytest.mark.parametrize(
    "path",
    [
        None,
        3,
        "",
        "/apps/x.py",
        "apps//x.py",
        "apps/../x.py",
        "apps/./x.py",
        "apps\\x.py",
        "apps/x\x00.py",
        "apps/x\n.py",
        " apps/x.py",
    ],
)
def test_invalid_paths(path):
    assert "evidence:path" in classify(path)["reasons"]
    assert "evidence:rename" in classify("apps/x.py", "renamed", path)["reasons"]


@pytest.mark.parametrize(
    "files,contents,count,truncated,reason",
    [
        (None, {}, 0, False, "evidence:records"),
        ("apps/x.py", {}, 0, False, "evidence:records"),
        ([], {}, 1, False, "evidence:count"),
        ([], {}, True, False, "evidence:count"),
        ([], {}, -1, False, "evidence:count"),
        ([], {}, None, False, "evidence:count"),
        ([], {}, 0, True, "evidence:truncated"),
        ([], {}, 0, None, "evidence:truncation-flag"),
        ([], None, 0, False, "evidence:contents"),
        ([{"filename": "apps/x.py", "status": "modified"}], {}, 1, False, "evidence:contents"),
        (
            [{"filename": "apps/x.py", "status": "added"}],
            {"apps/x.py": b"bytes"},
            1,
            False,
            "evidence:contents",
        ),
        ([{"filename": "apps/x.py", "status": "removed"}] * 2, {}, 2, False, "evidence:duplicate"),
    ],
)
def test_incomplete_evidence(files, contents, count, truncated, reason):
    result = classify_changed_files(files, contents, changed_files=count, truncated=truncated)
    assert result["class"] == "escalation" and reason in result["reasons"]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("apps/.env", ["protected:secrets"]),
        ("apps/billing/config.json", ["protected:name:billing"]),
        ("apps/payment/config.json", ["protected:name:payment"]),
        ("apps/purchase.py", ["protected:name:purchase"]),
        (
            "scripts/data-changes/production-membership.py",
            ["path:unknown-root", "protected:automation"],
        ),
        ("apps/deletion.py", ["protected:name:deletion"]),
    ],
)
@pytest.mark.parametrize(
    "direction", ["modified", "rename-in", "rename-out", "missing", "ambiguous"]
)
def test_owner_only_fixtures_fail_closed_with_exact_stable_reasons(path, expected, direction):
    record = {"filename": path, "status": "modified"}
    if direction == "rename-in":
        record.update(status="renamed", previous_filename="apps/ordinary.py")
    elif direction == "rename-out":
        record.update(filename="apps/ordinary.py", status="renamed", previous_filename=path)
    elif direction == "missing":
        record.update(status="renamed")
        expected = ["evidence:rename", *expected]
    elif direction == "ambiguous":
        record.update(previous_filename="apps/ordinary.py")
        expected = ["evidence:rename", *expected]
    result = classify_changed_files([record], {record["filename"]: ""}, changed_files=1)
    assert result == {"class": "escalation", "reasons": sorted(expected)}


def test_purity_determinism_no_semantics_or_input_mutation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("classifier attempted external IO or input execution")

    files = [
        {"filename": "apps/ordinary.py", "status": "modified"},
        {"filename": "apps/payment.py", "status": "removed"},
        {"filename": "apps/payment-billing.py", "status": "removed"},
    ]
    contents = {"apps/ordinary.py": "import os; os.system('fictional'); billing score deletion"}
    with monkeypatch.context() as patch:
        for target, name in [
            (builtins, "open"),
            (builtins, "exec"),
            (builtins, "eval"),
            (os, "system"),
            (socket, "socket"),
            (builtins, "__import__"),
        ]:
            patch.setattr(target, name, forbidden)
        results = [
            classify_changed_files(records, contents, changed_files=len(records))
            for records in (files, files[::-1], files[:1])
        ]
    expected = {
        "class": "escalation",
        "reasons": ["protected:name:billing", "protected:name:payment"],
    }
    assert results[:2] == [expected, expected]
    assert results[2] == {
        "class": "routine",
        "reasons": [],
    }
    assert files[1] == {"filename": "apps/payment.py", "status": "removed"}
    assert contents["apps/ordinary.py"].startswith("import os;")
