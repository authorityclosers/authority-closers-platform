#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
T=asr/openrouter_google_gemini-3.1-flash-lite/phone_8k
$R text --shape today --model google/gemini-3.8-flash --transcript $T
D=../results/text/today/google_gemini-3.8-flash/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1
$R judge --result $D --judge anthropic/claude-haiku-5.5
$R rjudge --result $D --judge anthropic/claude-haiku-5.5
