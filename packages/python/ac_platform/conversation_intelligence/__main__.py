"""Local acoustic inspection; never contacts a transcription or AI provider."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Sales Xray offline evidence tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Report tool presence without reading credentials")
    inspect = commands.add_parser("inspect", help="Inspect authorized audio locally")
    inspect.add_argument("source", type=Path)
    inspect.add_argument("--out", type=Path, required=True)
    inspect.add_argument("--rate", choices=(16000, 48000), type=int, default=16000)
    args = parser.parse_args()
    if args.command == "doctor":
        print(
            json.dumps(
                {
                    "ffmpeg": bool(shutil.which("ffmpeg")),
                    "ffprobe": bool(shutil.which("ffprobe")),
                    "provider_calls": False,
                }
            )
        )
        return 0
    from ac_platform.conversation_intelligence.signals import inspect_media

    try:
        receipt = inspect_media(args.source, args.out, rate=args.rate)
    except (ValueError, RuntimeError, OSError):
        # Third-party decoder errors may contain source paths or private metadata.
        print("Local inspection failed; verify the media and offline toolchain.", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "state": "acoustic_checkpoint_created",
                "provider_calls": False,
                "source_sha256": receipt.get("source_sha256"),
                "feature_sha256": receipt.get("feature_sha256"),
                "numeric_score": None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
