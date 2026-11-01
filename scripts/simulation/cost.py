"""What the lab's calls cost in AI, priced by the app's own cost engine. Read-only.

    cost.py <usage.json> <results-dir>

Reads the metrics store's usage export (``/srv/authority-closers/metrics/<env>/usage.json``,
written every five minutes by ac-metrics-collect) and the lab's ``<results>/S*.json``, and
prices every provider step of each lab call with ``cost_metrics.parse_export``: the same list
prices as Admin's cost meter. Prints one JSON line per call and a total. Needs the app's
Python environment (``ac_platform`` importable); never reads the database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def price_calls(document: dict[str, Any], ids: dict[str, str]) -> list[dict[str, Any]]:
    """``ids``: scenario id to recording id."""
    from ac_platform.conversation_intelligence.cost_metrics import parse_export

    export = parse_export(str(document.get("environment") or "development"), document)
    calls = {call.id: call for call in export.calls}
    rows: list[dict[str, Any]] = []
    for scenario, recording in sorted(ids.items()):
        call = calls.get(recording)
        steps = [step for step in export.steps if step.call == recording]
        priced = [step.paise for step in steps if step.paise is not None]
        audio_ms = call.audio_ms if call else 0
        paise = sum(priced)
        rows.append(
            {
                "id": scenario,
                "recording_id": recording,
                "in_store": call is not None,
                "audio_min": round(audio_ms / 60000, 2),
                "billed_s": call.billed_s if call else None,
                "report": bool(call and call.report_at),
                "steps": [
                    {
                        "stage": step.stage,
                        "model": step.model,
                        "status": step.status,
                        "paise": step.paise,
                    }
                    for step in steps
                ],
                "unpriced_steps": len(steps) - len(priced),
                "rupees": round(paise / 100, 2),
                "rupees_per_min": round(paise / 100 / (audio_ms / 60000), 3) if audio_ms else None,
            }
        )
    return rows


def main() -> None:
    document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    ids: dict[str, str] = {}
    for file in sorted(Path(sys.argv[2]).glob("S*.json")):
        run = json.loads(file.read_text(encoding="utf-8"))
        # The store keys a call by its recording, which the progress and report name.
        recording = (run.get("progress") or {}).get("recording_id") or (
            run.get("report") or {}
        ).get("recording_id")
        if recording:
            ids[run["id"]] = str(recording)
    rows = price_calls(document, ids)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    minutes = sum(row["audio_min"] for row in rows if row["in_store"])
    rupees = sum(row["rupees"] for row in rows)
    print(
        json.dumps(
            {
                "calls": len(rows),
                "in_store": sum(row["in_store"] for row in rows),
                "audio_min": round(minutes, 2),
                "rupees": round(rupees, 2),
                "rupees_per_min": round(rupees / minutes, 3) if minutes else None,
                "store_generated_at": document.get("generated_at"),
            }
        )
    )


if __name__ == "__main__":
    main()
