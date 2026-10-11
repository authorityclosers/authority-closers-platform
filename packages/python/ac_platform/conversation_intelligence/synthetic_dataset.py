"""Read-only browser over the fictional synthetic-v1 dataset (AUT-1798).

The dataset is a folder of fictional calls (MANIFEST.csv, transcripts and
answer keys), mounted read-only where configured. Nothing here touches
conversation state, real teams or providers; every answer says it is
synthetic. Answer keys are served without ``fixture_truth``, which the
dataset marks as never-a-call-fact. Paths come only from the manifest and must
stay inside the dataset folder.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationError,
    ConversationNotFound,
)

LABEL = "Synthetic test data: fictional people and companies, never a real team."
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PAGE = 100
_CALL_ID = re.compile(r"^syn-[A-Za-z0-9-]{3,120}$")
_ROW_FIELDS = (
    "call_id",
    "business_id",
    "journey_id",
    "rep_id",
    "at",
    "sequence",
    "language_mix",
    "scenario",
    "outcome",
    "crm_stage",
    "deal_value_inr",
    "duration_ms",
    "audio_status",
)
_HIDDEN_KEYS = frozenset({"fixture_truth"})


class SyntheticDatasetUnavailable(ConversationError):
    status = 503


def _row(raw: dict[str, str]) -> dict[str, Any]:
    row: dict[str, Any] = {name: raw.get(name) or None for name in _ROW_FIELDS}
    for name in ("sequence", "deal_value_inr", "duration_ms"):
        try:
            row[name] = int(raw.get(name) or "")
        except ValueError:
            row[name] = None
    return row


class SyntheticDataset:
    def __init__(self, root: str | Path | None) -> None:
        self.root = None if root is None else Path(root).resolve()

    def _require(self) -> Path:
        if self.root is None or not (self.root / "MANIFEST.csv").is_file():
            raise SyntheticDatasetUnavailable(
                "The synthetic dataset isn't mounted in this environment."
            )
        return self.root

    def _manifest(self) -> list[dict[str, str]]:
        root = self._require()
        with (root / "MANIFEST.csv").open(encoding="utf-8", newline="") as handle:
            return [
                row for row in csv.DictReader(handle) if _CALL_ID.fullmatch(row.get("call_id", ""))
            ]

    def _read(self, relative: str | None) -> Any:
        root = self._require()
        if not relative:
            return None
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path.suffix != ".json" or not path.is_file():
            return None
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ConversationConflict("This synthetic file is larger than the browser reads.")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ConversationConflict("This synthetic file couldn't be read.") from None

    def index(
        self,
        *,
        business: str | None = None,
        language: str | None = None,
        outcome: str | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not 1 <= limit <= MAX_PAGE or offset < 0:
            raise ConversationError("Use a page of 1 to 100 calls.")
        rows = [_row(raw) for raw in self._manifest()]
        facets = {
            "businesses": Counter(row["business_id"] for row in rows if row["business_id"]),
            "languages": Counter(row["language_mix"] for row in rows if row["language_mix"]),
            "outcomes": Counter(row["outcome"] for row in rows if row["outcome"]),
        }
        needle = (query or "").strip().lower()
        matched = [
            row
            for row in rows
            if (business is None or row["business_id"] == business)
            and (language is None or row["language_mix"] == language)
            and (outcome is None or row["outcome"] == outcome)
            and (not needle or needle in " ".join(str(value) for value in row.values()).lower())
        ]
        matched.sort(key=lambda row: (row["at"] or "", row["call_id"]), reverse=True)
        return {
            "synthetic": True,
            "label": LABEL,
            "total": len(matched),
            "dataset_total": len(rows),
            "items": matched[offset : offset + limit],
            "next_offset": offset + limit if offset + limit < len(matched) else None,
            "facets": {
                name: [
                    {"value": value, "count": count}
                    for value, count in sorted(
                        counter.items(), key=lambda item: (-item[1], item[0])
                    )
                ]
                for name, counter in facets.items()
            },
        }

    def call(self, call_id: str) -> dict[str, Any]:
        if not _CALL_ID.fullmatch(call_id):
            raise ConversationNotFound("Synthetic call not found.")
        raw = next((row for row in self._manifest() if row["call_id"] == call_id), None)
        if raw is None:
            raise ConversationNotFound("Synthetic call not found.")
        loaded = self._read(raw.get("transcript"))
        # A file that parses but isn't an object reads as an empty transcript.
        transcript: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
        key = self._read(raw.get("answer_key"))
        raw_lines = transcript.get("lines")
        lines = []
        for line in raw_lines if isinstance(raw_lines, list) else []:
            if isinstance(line, dict):
                lines.append(
                    {
                        name: line.get(name)
                        for name in (
                            "line_id",
                            "speaker",
                            "text",
                            "phase",
                            "annotations",
                            "start_ms",
                            "end_ms",
                        )
                    }
                )
        answer = (
            {name: value for name, value in key.items() if name not in _HIDDEN_KEYS}
            if isinstance(key, dict)
            else None
        )
        return {
            "synthetic": True,
            "label": LABEL,
            "call": _row(raw),
            "participants": [
                item for item in transcript.get("participants") or [] if isinstance(item, dict)
            ]
            if isinstance(transcript.get("participants"), list)
            else [],
            "lines": lines,
            "answer_key": answer,
        }
