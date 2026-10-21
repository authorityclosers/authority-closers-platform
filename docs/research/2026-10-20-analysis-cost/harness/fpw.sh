#!/bin/bash
# round-8 worker: usage fpw.sh <variant> [calls...]
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
nice -n 19 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python fullpass.py "$@"
echo "fpw $1 finished"
