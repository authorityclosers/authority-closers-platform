"""Concurrent artifact pagination must not undermine pool admission proofs."""

from __future__ import annotations

import json
import runpy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
READER = runpy.run_path(str(ROOT / "infra/release/read-artifact-inventory.py"))
RECLAIMER = runpy.run_path(str(ROOT / "infra/release/reclaim-artifact-pool.py"))
START = datetime(2026, 10, 11, tzinfo=UTC)


def artifact(identity: int, *, size: int = 10, recent: bool = False) -> dict:
    return {
        "id": identity,
        "name": f"diagnostic-{identity}",
        "size_in_bytes": size,
        "expired": False,
        "created_at": "2099-01-01T00:00:00Z" if recent else "2026-10-01T00:00:00Z",
    }


def snapshot():
    return READER["InventorySnapshot"](START)


def changing_pages() -> list[dict]:
    older = [artifact(identity) for identity in range(201, 0, -1)]
    # One upload before each subsequent request shifts the older rows right.
    return [
        {"total_count": 201, "artifacts": older[:100]},
        {"total_count": 202, "artifacts": older[99:199]},
        {"total_count": 203, "artifacts": older[198:]},
    ]


def complete_pages(items: list[dict]) -> list[dict]:
    return [
        {"total_count": len(items), "artifacts": items[start : start + 100]}
        for start in range(0, max(1, len(items)), 100)
    ]


def test_uploads_between_pages_deduplicate_without_losing_older_bytes() -> None:
    state = snapshot()
    with pytest.raises(ValueError, match="unobserved artifacts"):
        READER["validate_inventory"](json.dumps(changing_pages()), snapshot=state)
    recovered = [artifact(203, recent=True), artifact(202, recent=True)]
    recovered.extend(artifact(identity) for identity in range(201, 0, -1))
    all_items, pages = READER["validate_inventory"](
        json.dumps(complete_pages(recovered)), snapshot=state
    )
    assert len(all_items) == 203
    items = [item for item in all_items if item["id"] <= 201]
    assert pages == 3
    assert len(items) == 201
    assert {item["id"] for item in items} == set(range(1, 202))
    assert sum(item["size_in_bytes"] for item in items) == 2010


def test_recent_uploads_are_outside_proof_but_observed_bytes_still_count() -> None:
    older = [artifact(identity) for identity in range(100, 0, -1)]
    recent = artifact(101, size=500, recent=True)
    pages = [
        {"total_count": 101, "artifacts": [recent, *older[:99]]},
        {"total_count": 101, "artifacts": older[-1:]},
    ]
    state = snapshot()
    items, _ = READER["validate_inventory"](json.dumps(pages), snapshot=state)
    assert state.expected_count == 100
    assert len(state.known) == 100
    assert len(items) == 101
    assert sum(item["size_in_bytes"] for item in items) == 1500


def test_older_disappearance_between_pages_fails_closed() -> None:
    older = [artifact(identity) for identity in range(201, 0, -1)]
    pages = [
        {"total_count": 201, "artifacts": older[:100]},
        {"total_count": 200, "artifacts": older[101:]},
    ]
    with pytest.raises(ValueError, match="incomplete inventory"):
        READER["validate_inventory"](json.dumps(pages), snapshot=snapshot())


def test_recent_upload_size_churn_uses_largest_observed_size() -> None:
    older = [artifact(identity) for identity in range(100, 0, -1)]
    recent = artifact(101, size=500, recent=True)
    pages = [
        {"total_count": 101, "artifacts": [recent, *older[:99]]},
        {"total_count": 102, "artifacts": [{**recent, "size_in_bytes": 1}, older[-1]]},
    ]
    state = snapshot()
    with pytest.raises(ValueError, match="unobserved artifacts"):
        READER["validate_inventory"](json.dumps(pages), snapshot=state)
    recovered = [{**recent, "size_in_bytes": 1}, *older]
    items, _ = READER["validate_inventory"](json.dumps(complete_pages(recovered)), snapshot=state)
    assert len(items) == 101
    assert sum(item["size_in_bytes"] for item in items) == 1500


def test_duplicate_recent_ids_cannot_hide_a_missing_older_artifact() -> None:
    recent = artifact(1, recent=True)
    pages = [{"total_count": 2, "artifacts": [recent, recent]}]
    with pytest.raises(ValueError, match="incomplete inventory"):
        READER["validate_inventory"](json.dumps(pages), snapshot=snapshot())


def test_second_precision_does_not_misclassify_an_inflight_upload_as_older() -> None:
    older = [artifact(identity) for identity in range(100, 0, -1)]
    recent = {**artifact(101, size=500), "created_at": START.isoformat()}
    state = READER["InventorySnapshot"](START.replace(microsecond=500000))
    pages = [
        {"total_count": 101, "artifacts": [recent, *older[:99]]},
        {"total_count": 102, "artifacts": [{**recent, "size_in_bytes": 600}, older[-1]]},
    ]
    with pytest.raises(ValueError, match="unobserved artifacts"):
        READER["validate_inventory"](json.dumps(pages), snapshot=state)
    items, _ = READER["validate_inventory"](
        json.dumps(complete_pages([recent, *older])), snapshot=state
    )
    assert state.expected_count == 100
    assert len(state.known) == 100
    assert sum(item["size_in_bytes"] for item in items) == 1600


def test_duplicate_older_size_change_fails_closed() -> None:
    pages = changing_pages()
    pages[1]["artifacts"][0] = {**pages[1]["artifacts"][0], "size_in_bytes": 1}
    with pytest.raises(READER["SnapshotChanged"], match="size changed"):
        READER["validate_inventory"](json.dumps(pages), snapshot=snapshot())


def test_retry_keeps_original_boundary_and_does_not_accept_a_shrunk_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = [artifact(identity) for identity in range(101, 0, -1)]
    responses = iter(
        [
            [{"total_count": 101, "artifacts": older[:100]}],
            [{"total_count": 100, "artifacts": older[:100]}],
            [{"total_count": 100, "artifacts": older[:100]}],
        ]
    )
    sleeps = []
    monkeypatch.setattr(READER["time"], "sleep", sleeps.append)
    with pytest.raises(ValueError, match="exhausted 3 attempts"):
        READER["read_inventory"](
            "/fixture/gh",
            "fixture/repository",
            "admission",
            fetch=lambda: json.dumps(next(responses)),
        )
    assert sleeps == [2, 4]


def test_retry_rechecks_sizes_seen_in_an_incomplete_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = [artifact(identity) for identity in range(101, 0, -1)]
    changed = [{**older[0], "size_in_bytes": 1}, *older[1:100]]
    responses = iter(
        [
            [{"total_count": 101, "artifacts": older[:100]}],
            [
                {"total_count": 101, "artifacts": changed},
                {"total_count": 101, "artifacts": older[100:]},
            ],
        ]
    )
    monkeypatch.setattr(READER["time"], "sleep", lambda _: None)
    with pytest.raises(READER["SnapshotChanged"]):
        READER["read_inventory"](
            "/fixture/gh",
            "fixture/repository",
            "admission",
            fetch=lambda: json.dumps(next(responses)),
        )


@pytest.mark.parametrize("still_present", [True, False])
def test_retry_preserves_recent_size_bound(
    monkeypatch: pytest.MonkeyPatch, still_present: bool
) -> None:
    older = [artifact(identity) for identity in range(100, 0, -1)]
    recent = artifact(101, size=500, recent=True)
    completed = (
        [
            {"total_count": 101, "artifacts": [{**recent, "size_in_bytes": 1}, *older[:99]]},
            {"total_count": 101, "artifacts": older[-1:]},
        ]
        if still_present
        else [{"total_count": 100, "artifacts": older}]
    )
    responses = iter([[{"total_count": 101, "artifacts": [recent, *older[:99]]}], completed])
    monkeypatch.setattr(READER["time"], "sleep", lambda _: None)
    items = READER["read_inventory"](
        "/fixture/gh",
        "fixture/repository",
        "admission",
        fetch=lambda: json.dumps(next(responses)),
    )
    assert {item["id"] for item in items} == set(range(1, 102))
    assert sum(item["size_in_bytes"] for item in items) == 1500
    assert RECLAIMER["projection"](items, 100, None) == 1600


def test_reader_retries_transient_missing_page_then_accepts_upload_churn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = changing_pages()
    recovered = [artifact(203, recent=True), artifact(202, recent=True)]
    recovered.extend(artifact(identity) for identity in range(201, 0, -1))
    responses = iter([pages[:1], pages, complete_pages(recovered)])
    sleeps = []
    monkeypatch.setattr(READER["time"], "sleep", sleeps.append)
    items = READER["read_inventory"](
        "/fixture/gh",
        "fixture/repository",
        "admission",
        fetch=lambda: json.dumps(next(responses)),
    )
    assert len(items) == 203
    assert {item["id"] for item in items} == set(range(1, 204))
    assert sleeps == [2, 4]


def test_unobserved_uploads_exhaust_retries_without_publishing_bytes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []
    sleeps = []

    def fetch() -> str:
        calls.append(True)
        return json.dumps(changing_pages())

    monkeypatch.setattr(READER["time"], "sleep", sleeps.append)
    with pytest.raises(ValueError, match="exhausted 3 attempts"):
        READER["read_inventory"]("/fixture/gh", "fixture/repository", "admission", fetch=fetch)
    assert len(calls) == 3
    assert sleeps == [2, 4]
    output = capsys.readouterr()
    assert output.out == ""
    assert "complete pages=" not in output.err
    assert output.err.count("unobserved artifacts") == 3


@pytest.mark.parametrize("created", [None, "invalid", "2026-10-01T00:00:00", 1])
def test_created_at_is_required_for_boundary_proof(created: object) -> None:
    item = {**artifact(1), "created_at": created}
    with pytest.raises(ValueError, match="created_at"):
        READER["validate_inventory"](
            json.dumps([{"total_count": 1, "artifacts": [item]}]), snapshot=snapshot()
        )


def test_snapshot_boundary_hidden_by_uploads_refuses_to_guess() -> None:
    pages = [{"total_count": 101, "artifacts": [artifact(i, recent=True) for i in range(1, 101)]}]
    with pytest.raises(ValueError, match="boundary is not visible"):
        READER["validate_inventory"](json.dumps(pages), snapshot=snapshot())


def test_reclaimer_uses_the_same_concurrent_pagination_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = RECLAIMER["GitHub"]("fixture/repository")
    recovered = [artifact(203, recent=True), artifact(202, recent=True)]
    recovered.extend(artifact(identity) for identity in range(201, 0, -1))
    responses = iter([changing_pages(), complete_pages(recovered)])
    monkeypatch.setattr(github, "api", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(RECLAIMER["INVENTORY"]["time"], "sleep", lambda _: None)
    items = github.artifacts()
    assert len(items) == 203
    assert sum(item["size_in_bytes"] for item in items) == 2030


def test_only_diagnostic_retention_changes() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/application.yml").read_text())
    uploads = {
        step["with"]["name"]: step["with"]["retention-days"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    }
    assert len(uploads) == 4
    for name, days in uploads.items():
        # The reduction belongs to the ordered follow-up after #442 and #437.
        assert days == (1 if name.startswith("ac-application-") else 14)
