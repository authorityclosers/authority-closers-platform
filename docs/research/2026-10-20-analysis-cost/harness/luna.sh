#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
for t in asr/openrouter_google_gemini-3.1-flash-lite/phone_8k asr/openrouter_google_gemini-3.8-flash/phone_8k asr/sarvam_saaras-v4/phone_8k; do
  $R text --shape onepass --model openai/gpt-6-luna --transcript $t
done
$R text --shape onepass --model openai/gpt-6-luna --run 2
$R text --shape onepass2 --model google/gemini-3.8-flash --run 2
