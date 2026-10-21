#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
D=../results/text/onepass/google_gemini-3.1-flash-lite/oracle/run1
nice -n 19 $PY run.py judge --result $D --judge anthropic/claude-haiku-5.5
nice -n 19 $PY run.py judge --result $D --judge google/gemini-3.8-flash
nice -n 19 $PY run.py rjudge --result $D --judge anthropic/claude-haiku-5.5
nice -n 19 $SPY score.py facts
nice -n 19 $SPY score.py report
