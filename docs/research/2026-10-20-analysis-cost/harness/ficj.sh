#!/bin/bash
# Haiku fact + report judges for the fictional Brain 4.0 Luna run (same judge as every other fictional arm)
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PYB="nice -n 19 ionice -c3 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python"
D=../results/text/brain4/openai_gpt-6-luna/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1
$PYB run.py judge --result $D --judge anthropic/claude-haiku-5.5
$PYB run.py rjudge --result $D --judge anthropic/claude-haiku-5.5
echo ficj-finished
