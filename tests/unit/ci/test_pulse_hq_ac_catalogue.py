"""The Pulse HQ data change maps every AC catalogue feature into rows Pulse's checks accept,
keeps a dry run a dry run, and refuses to apply without the approval's words."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "pulse_hq_ac_catalogue", ROOT / "scripts/data-changes/pulse-hq-ac-catalogue.py"
)
assert spec is not None and spec.loader is not None
change = importlib.util.module_from_spec(spec)
sys.modules["pulse_hq_ac_catalogue"] = change
spec.loader.exec_module(change)

CATALOGUE = json.loads(change.CATALOGUE.read_text(encoding="utf-8"))


def test_every_feature_fits_pulse_hq_feature_checks() -> None:
    rows = change.rows(CATALOGUE)
    assert len(rows) == len(CATALOGUE["features"])
    assert len({r["key"] for r in rows}) == len(rows)
    for row in rows:
        # pulse.hq_feature's own constraints (Pulse migration 0944).
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", row["key"])
        assert row["category"] in change.HQ_CATEGORIES
        assert 2 <= len(row["name"].strip()) <= 80
        assert len(row["promise"]) <= 200 and len(row["what"]) <= 600
        assert len(row["who"]) <= 120 and len(row["proof"]) <= 300
        assert row["status"] in {"live", "beta", "building", "idea"}
        assert re.fullmatch(r"[A-Z][A-Za-z0-9]{1,40}", row["icon"])
        # Pulse links the first " /path" of a proof line inside Pulse; AC's must have none.
        assert not re.search(r"(?:^|[\s,;(])/[a-z]", row["proof"]), row["proof"]
    assert set(change.CATEGORY_TO_HQ) == {c["id"] for c in CATALOGUE["categories"]}


def test_status_follows_the_code() -> None:
    by_key = {r["key"]: r for r in change.rows(CATALOGUE)}
    for feature in CATALOGUE["features"]:
        expected = (
            "idea"
            if feature["status"] == "planned"
            else "beta"
            if feature["status"] == "dev" or feature.get("switch")
            else "live"
        )
        assert by_key[feature["id"]]["status"] == expected, feature["id"]
        assert by_key[feature["id"]]["proof"].startswith("AC: ")


def test_dry_run_rolls_back_and_apply_commits() -> None:
    rows = change.rows(CATALOGUE)
    dry = change.sql(rows, actor="x", apply=False)
    real = change.sql(rows, actor="x", apply=True)
    assert "\nrollback;\n" in dry and "\ncommit;\n" not in dry
    assert "\ncommit;\n" in real and "\nrollback;\n" not in real
    assert dry.count("begin;") == 1 and "pulse_hq" in dry


def test_apply_needs_the_approval(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        change.main(["--apply", "--approver", "Owner"])
    assert "--words" in capsys.readouterr().err
