#!/bin/bash
# Round 2: GPT-6 Luna, coaching walk-through prompt (v3), on the Gemini 3.1 Flash-Lite transcripts; Haiku judges.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
T=asr/openrouter_google_gemini-3.1-flash-lite/phone_8k
$R text --shape onepass3 --model openai/gpt-6-luna --transcript $T
D=../results/text/onepass3/openai_gpt-6-luna/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1
$R judge --result $D --judge anthropic/claude-haiku-5.5
$R rjudge --result $D --judge anthropic/claude-haiku-5.5
