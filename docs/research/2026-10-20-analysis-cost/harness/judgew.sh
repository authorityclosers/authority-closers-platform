#!/bin/bash
# judge worker: usage judgew.sh <round 3|4|5|6> <judge model>
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
[ "$1" = "3" ] || export RC_ROUND=$1
RC_JUDGES=$2 nice -n 19 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python realcalls.py judge
