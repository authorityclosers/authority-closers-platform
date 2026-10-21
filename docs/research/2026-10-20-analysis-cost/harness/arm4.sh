#!/bin/bash
# one round-4 arm on the real calls (parallel worker); usage: arm4.sh <model>
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
nice -n 19 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python - "$1" <<'PY'
import argparse, sys
import realcalls as RC, run as R
R.cmd_text(argparse.Namespace(shape="brain4", model=sys.argv[1], transcript=RC.TRANSCRIPT, run=1, calls=RC.ids(), force=False))
PY
