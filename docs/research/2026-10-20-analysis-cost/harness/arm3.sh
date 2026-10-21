#!/bin/bash
# one round-3 arm on the real calls (parallel worker); usage: arm3.sh <shape> <model> [reverse]
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
nice -n 19 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python - "$@" <<'PY'
import argparse, sys
import realcalls as RC, run as R
calls = RC.ids()[::-1] if sys.argv[3:4] == ["reverse"] else RC.ids()
R.cmd_text(argparse.Namespace(shape=sys.argv[1], model=sys.argv[2], transcript=RC.TRANSCRIPT, run=1, calls=calls, force=False))
PY
