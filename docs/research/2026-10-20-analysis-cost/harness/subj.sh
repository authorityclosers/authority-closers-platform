#!/bin/bash
# subscription judge worker: usage subj.sh <judge|rjudge> <result dir> [claude-sub/haiku]
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:. PATH=/home/acdev/.local/bin:/usr/bin:/bin
nice -n 19 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python run.py $1 --result $2 --judge ${3:-claude-sub/haiku}
echo "subj $1 $2 finished"
