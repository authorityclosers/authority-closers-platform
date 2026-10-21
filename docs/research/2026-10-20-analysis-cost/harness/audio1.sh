#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
nice -n 19 ionice -c3 $PY run.py audio1 --model google/gemini-3.1-flash-lite --variant phone_8k
