#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
D=../results/asr/sarvam_saaras-v4/phone_8k
for c in fx-04 fx-05 fx-08 fx-09 fx-16; do
  rm -f $D/$c.json $D/retain/anthropic_claude-haiku-5.5/$c.json
  nice -n 19 $SPY sarvam_asr.py --variant phone_8k --calls $c
  sleep 20
done
nice -n 19 $PY run.py retain --result $D --judge anthropic/claude-haiku-5.5
$SPY score.py retain > ../results/scores/retain.md; $SPY score.py asr > ../results/scores/asr.md
