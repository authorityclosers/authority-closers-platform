#!/bin/bash
# subscription judge worker (Claude Code CLI, Sonnet): usage sjw.sh <shape:model> ...
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:. PATH=/home/acdev/.local/bin:/usr/bin:/bin
nice -n 19 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python subjudge.py "$@"
echo sjw-finished
