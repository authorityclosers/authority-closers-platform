#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
for m in gemini-3.1-flash-lite gemini-3.8-flash gemini-3.5-flash-lite; do nice -n 19 $PY run.py asr --arm openrouter:google/$m --variant phone_8k --calls fx-09; done
