#!/usr/bin/env python3
"""Build an internal 60-call readiness/quality scorecard from private local evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from ac_platform.conversation_intelligence.processing_cli import _Parser
from ac_platform.conversation_intelligence.synthetic_quality import build_scorecard


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        dataset = args.dataset.resolve()
        with (dataset / "MANIFEST.csv").open() as stream:
            rows = [
                row for row in csv.DictReader(stream) if row["audio_selected"].lower() == "true"
            ]
        reviews = {}
        if len(rows) != 60:
            raise ValueError("The initial audio-selected batch must contain exactly 60 calls.")
        for row in rows:
            if row["synthetic"].lower() != "true" or not re.fullmatch(
                r"syn-[A-Za-z0-9_-]+", row["call_id"]
            ):
                raise ValueError("Only the stable synthetic batch is accepted.")
            paths = {name: (dataset / row[name]).resolve() for name in ("audio", "answer_key")}
            if any(not path.is_relative_to(dataset) for path in paths.values()):
                raise ValueError("Every source must stay in the synthetic dataset.")
            row["audio_present"] = paths["audio"].is_file()
            if args.reviews:
                path = args.reviews / f"{row['call_id']}.json"
                if path.is_file():
                    review = json.loads(path.read_text())
                    if (
                        review.get("answer_key_sha256")
                        != hashlib.sha256(paths["answer_key"].read_bytes()).hexdigest()
                    ):
                        raise ValueError("The answer key changed after this review.")
                    reviews[row["call_id"]] = review
        result = build_scorecard(rows, reviews)
        with args.output.open("x", encoding="utf-8") as stream:
            os.chmod(args.output, 0o600)
            json.dump(result, stream, indent=2)
            stream.write("\n")
    except (ValueError, OSError, KeyError, TypeError):
        print(
            "Scorecard unavailable; check the synthetic batch and bound review receipts.",
            file=sys.stderr,
        )
        return 2
    print(f"Internal scorecard: {len(rows)} selected calls, {len(reviews)} review receipts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
