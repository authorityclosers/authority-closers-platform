#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
N="nice -n 19 ionice -c3"
for v in clean_16k phone_8k; do
  for m in whisper-large-v3-turbo whisper-large-v3; do $N $PY run.py asr --arm groq:$m --variant $v --calls rs-fleurs-hi rs-fleurs-mr; done
done
calls=$(cd ../bench/audio && ls -d fx-* | tr '\n' ' ')
for m in whisper-large-v3-turbo whisper-large-v3; do $N $PY run.py asr --arm groq:$m --variant phone_8k --calls $calls; done
