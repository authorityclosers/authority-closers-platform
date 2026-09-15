"""Fixed subprocess entrypoint for :mod:`inference_broker`.

The module accepts no user-selected provider command or shell text.  A trusted
launcher invokes it with ``--child`` and the private frame arrives on stdin.
"""

from __future__ import annotations

import sys

from ac_platform.conversation_intelligence.inference_broker import child_main


def main() -> int:
    if sys.argv[1:] != ["--child"]:
        return 2
    return child_main()


if __name__ == "__main__":
    raise SystemExit(main())
