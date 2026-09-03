"""Package-native HTTP server runner with a Windows-safe database event loop."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--reload", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    uvicorn.run(
        "ac_platform.http.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="ac_platform.application.asyncio_runtime:compatible_event_loop_factory",
    )
    return 0


__all__ = ["main"]
