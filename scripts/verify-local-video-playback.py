"""Retired browser proof: a side-effect-free help-only compatibility entry point.

The unsafe existing-tab workflow is not retained as an executable fallback.
This shim never imports browser tooling or runs the replacement.
"""

from __future__ import annotations

import sys

NOTICE = (
    "Retired: verify-local-video-playback.py is help-only.\n"
    "It does not connect to a browser, run commands, or write evidence.\n"
    "Replacement: scripts/verify-local-adaptive-video.mjs.\n"
    "Inspect that separate script before an explicitly authorized run using\n"
    "--run-authorized-local-hls-proof. It requires an already-running local\n"
    "Chrome with a normally signed-in synthetic learner and owns a new tab.\n"
    "This entry point does not execute or forward arguments to the replacement.\n"
)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    sys.stdout.write(NOTICE)
    if arguments not in ([], ["--help"], ["-h"]):
        # Unknown input may contain credentials or signed URLs. Never echo it.
        sys.stderr.write("Retired command: execution arguments are not accepted.\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
