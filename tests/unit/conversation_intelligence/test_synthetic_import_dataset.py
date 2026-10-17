"""Dataset adapter used by the direct-DB sandbox loaders: exact folders and identities."""

import gzip
import json
from collections import Counter

import pytest

from ac_platform.conversation_intelligence.synthetic_import_dataset import (
    OPERATIONS,
    bundles,
    exact_file,
    master_records,
    summaries,
)
from tests.unit.conversation_intelligence.test_synthetic_import_contracts import bundle


def dataset(root):
    data = bundle()
    business = data["metadata"]["business_id"]
    call = data["metadata"]["call_id"]
    header = {"synthetic": True, "schema_version": "synthetic-sales-v1.0"}

    def write(path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))

    def compressed(path, rows):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")

    write("simulation/config.json", {"synthetic": True, "start": "2017-01-01"})
    compressed(
        "simulation/operations/business_history.jsonl.gz",
        [{**header, "business_id": business, "at": "2017-01-01T00:00:00+05:30"}],
    )
    write(f"world/{business}.json", {**header, "business_id": business})
    for name, *_ in OPERATIONS:
        compressed(f"simulation/operations/{name}.jsonl.gz", [])
    compressed(
        "simulation/calls/2017-01.jsonl.gz", [{**data["metadata"], "report": data["report"]}]
    )
    write(
        "import_ready/index.json",
        {
            "synthetic": True,
            "calls": 1,
            "bundles": [{"call_id": call, "folder": "import_ready/" + call}],
        },
    )
    for key in ("metadata", "transcript", "answer_key", "report", "coaching"):
        write(f"import_ready/{call}/{key}.json", data[key])
    return data


def test_indexed_folders_cannot_escape_the_dataset_or_change_call_identity(tmp_path):
    data = dataset(tmp_path)
    outside = tmp_path.parent / "outside-fictional.json"
    outside.write_text("{}")
    (tmp_path / "link.json").symlink_to(outside)
    with pytest.raises(ValueError, match="out-of-root"):
        exact_file(tmp_path, "link.json")
    with pytest.raises(ValueError, match="out-of-root"):
        exact_file(tmp_path, "../outside-fictional.json")
    path = tmp_path / "import_ready/index.json"
    path.write_text(
        json.dumps(
            {
                "synthetic": True,
                "calls": 1,
                "bundles": [{"call_id": data["metadata"]["call_id"], "folder": "../outside"}],
            }
        )
    )
    with pytest.raises(ValueError, match="folder identity"):
        list(bundles(tmp_path))


def test_adapter_reads_master_history_summaries_and_bundles_offline(tmp_path):
    data = dataset(tmp_path)
    counts = Counter(row.kind for row in (*master_records(tmp_path), *summaries(tmp_path)))
    assert counts == {"world": 1, "business_history": 1, "call_summary": 1}
    calls = list(bundles(tmp_path))
    assert [call.metadata["call_id"] for call in calls] == [data["metadata"]["call_id"]]
