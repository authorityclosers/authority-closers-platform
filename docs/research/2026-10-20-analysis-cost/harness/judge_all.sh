#!/bin/bash
# Judge every finished arm (>= 15 calls) once; resumable.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
for d in $(find ../results/text ../results/audio1 -type d -name 'run*' 2>/dev/null | sort); do
  [ "$(ls $d/fx-*.json 2>/dev/null | wc -l)" -ge 15 ] || { echo "not finished: $d"; continue; }
  $R judge --result $d --judge anthropic/claude-haiku-5.5
  $R rjudge --result $d --judge anthropic/claude-haiku-5.5
  case "$d" in *oracle*) $R judge --result $d --judge google/gemini-3.8-flash ;; esac
done
for w in facts report; do nice -n 19 $SPY score.py $w > ../results/scores/$w.md 2>&1; done
nice -n 19 $SPY score.py consistency > ../results/scores/consistency.md 2>&1
nice -n 19 $SPY score.py cost > ../results/scores/cost.md 2>&1
