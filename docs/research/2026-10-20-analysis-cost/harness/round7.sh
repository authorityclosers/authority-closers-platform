#!/bin/bash
# Round 7 (21 Oct): Brain 4.0 + measured pauses + the coach's timestamped moment notes; usage round7.sh <model>
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PYB="nice -n 19 ionice -c3 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python"
RC_NOTES=1 RC_MODELS=$1 $PYB realcalls.py brain4m
echo "round7 $1 analysed"
