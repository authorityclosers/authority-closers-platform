#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
rm -rf ../results/text/onepass/qwen_qwen3.8-flash ../results/text/onepass/z-ai_glm-5.3-flash ../results/text/onepass/deepseek_deepseek-v4.1-flash
for m in deepseek/deepseek-v4.1-flash z-ai/glm-5.3-flash xiaomi/mimo-v2.6-flash openai/gpt-oss-120b qwen/qwen3.8-flash; do
  $R text --shape onepass --model $m
done
