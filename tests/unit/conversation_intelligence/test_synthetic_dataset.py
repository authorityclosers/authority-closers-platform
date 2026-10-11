"""The synthetic dataset browser (AUT-1798) on a tiny fictional folder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.synthetic_dataset import (
    SyntheticDataset,
    SyntheticDatasetUnavailable,
)

HEADER = (
    "call_id,business_id,journey_id,rep_id,at,sequence,language_mix,scenario,outcome,"
    "crm_stage,deal_value_inr,duration_ms,audio_status,transcript,answer_key\n"
)


def _dataset(tmp_path: Path) -> Path:
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "keys").mkdir()
    rows = []
    for index, (business, language, outcome) in enumerate(
        [
            ("syn-saas", "hi-en", "Won"),
            ("syn-saas", "mr-en", "Lost"),
            ("syn-estate", "hi-en", "Won"),
        ]
    ):
        call_id = f"syn-x-J0{index}-C-01"
        (tmp_path / "transcripts" / f"{call_id}.json").write_text(
            json.dumps(
                {
                    "participants": [{"role": "rep", "name": "Fictional Rep"}],
                    "lines": [
                        {
                            "line_id": f"{call_id}:L001",
                            "speaker": "rep",
                            "text": "नमस्ते",
                            "start_ms": 0,
                            "end_ms": 900,
                            "secret": "x",
                        }
                    ],
                }
            )
        )
        (tmp_path / "keys" / f"{call_id}.json").write_text(
            json.dumps({"report": {"the_big_picture": {}}, "fixture_truth": {"hidden": True}})
        )
        rows.append(
            f"{call_id},{business},J{index},R1,2026-07-2{index}T10:00:00+05:30,1,{language},s,{outcome},Stage,1000,60000,none,transcripts/{call_id}.json,keys/{call_id}.json"
        )
    rows.append(
        "syn-x-J9-C-01,syn-saas,J9,R1,2026-07-01,1,en-IN,s,Won,S,1,1,none,../../etc/passwd.json,keys/missing.json"
    )
    (tmp_path / "MANIFEST.csv").write_text(HEADER + "\n".join(rows) + "\n")
    return tmp_path


def test_index_filters_searches_and_labels(tmp_path: Path) -> None:
    dataset = SyntheticDataset(_dataset(tmp_path))
    everything = dataset.index()
    assert everything["synthetic"] is True and "Synthetic" in everything["label"]
    assert everything["dataset_total"] == 4
    assert {"value": "syn-saas", "count": 3} in everything["facets"]["businesses"]
    assert [row["call_id"] for row in dataset.index(language="mr-en")["items"]] == [
        "syn-x-J01-C-01"
    ]
    assert dataset.index(business="syn-estate")["total"] == 1
    assert dataset.index(query="lost")["total"] == 1
    page = dataset.index(limit=2)
    assert len(page["items"]) == 2 and page["next_offset"] == 2
    assert everything["items"][0]["duration_ms"] == 60000


def test_call_detail_never_serves_fixture_truth_or_leaves_the_folder(tmp_path: Path) -> None:
    dataset = SyntheticDataset(_dataset(tmp_path))
    call = dataset.call("syn-x-J00-C-01")
    assert call["synthetic"] is True
    assert call["lines"][0]["text"] == "नमस्ते" and "secret" not in call["lines"][0]
    assert "fixture_truth" not in call["answer_key"]
    escaped = dataset.call("syn-x-J9-C-01")
    assert escaped["lines"] == [] and escaped["answer_key"] is None
    for bad in ("syn-nope-C-01", "../MANIFEST", "SYN-X"):
        with pytest.raises(ConversationNotFound):
            dataset.call(bad)


def test_unmounted_dataset_says_so(tmp_path: Path) -> None:
    for root in (None, tmp_path / "missing"):
        with pytest.raises(SyntheticDatasetUnavailable) as raised:
            SyntheticDataset(root).index()
        assert raised.value.status == 503
