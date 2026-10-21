#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
$R text --shape onepass2 --model openai/gpt-6-luna
$R text --shape onepass2 --model openai/gpt-6-luna --transcript asr/openrouter_google_gemini-3.1-flash-lite/phone_8k
for d in ../results/text/onepass2/openai_gpt-6-luna/oracle/run1 ../results/text/onepass2/openai_gpt-6-luna/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1; do
  $R judge --result $d --judge anthropic/claude-haiku-5.5; $R rjudge --result $d --judge anthropic/claude-haiku-5.5
done
