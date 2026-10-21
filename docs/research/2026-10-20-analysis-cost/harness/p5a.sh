#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
for m in google/gemini-3.1-flash-lite google/gemini-3.8-flash; do
  $R text --shape onepass2 --model $m
  D=../results/text/onepass2/${m/\//_}/oracle/run1
  $R judge --result $D --judge anthropic/claude-haiku-5.5
  $R rjudge --result $D --judge anthropic/claude-haiku-5.5
done
nice -n 19 $SPY score.py facts; nice -n 19 $SPY score.py report
