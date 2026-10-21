#!/bin/bash
# Round 3, Luna side (owner-approved 21 Oct: Azure zero-retention endpoint), then cross-judging and scores.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:. BENCH_STRICT=1 BENCH_OPENAI_HOSTS=azure
PY="nice -n 19 ionice -c3 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python realcalls.py"
A=/home/acdev/research/analysis-cost-20261020/realcalls/asr/openrouter_google_gemini-3.1-flash-lite/phone
for i in $(seq 1 120); do [ "$(ls $A 2>/dev/null | grep -cE '\.(json|failed)$')" -ge 7 ] && break; sleep 30; done
RC_PROVIDERS=openai $PY text && RC_PROVIDERS=openai $PY judge
for i in $(seq 1 240); do pgrep -f "harness/realcalls.sh" > /dev/null || break; sleep 30; done
RC_PROVIDERS=google,openai $PY judge && RC_PROVIDERS=google,openai $PY score > ../realcalls/scores.md
echo realcalls-luna-finished
