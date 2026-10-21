#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
for v in phone_8k clean_16k; do
  for m in gemini-3.8-flash gemini-3.1-flash-lite; do nice -n 19 $PY run.py asr --arm openrouter:google/$m --variant $v --calls rs-fleurs-hi rs-fleurs-mr; done
done
