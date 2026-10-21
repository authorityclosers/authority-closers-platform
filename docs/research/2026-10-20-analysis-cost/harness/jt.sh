#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
D=../results/text/today/google_gemini-3.8-flash/oracle/run1
R="nice -n 19 ionice -c3 $PY run.py"
$R judge --result $D --judge anthropic/claude-haiku-5.5 --force
$R judge --result $D --judge google/gemini-3.8-flash --force
$R rjudge --result $D --judge anthropic/claude-haiku-5.5 --force
nice -n 19 $SPY score.py facts > ../results/scores/facts.md; nice -n 19 $SPY score.py report > ../results/scores/report.md
grep -E "today|arm" ../results/scores/facts.md ../results/scores/report.md
