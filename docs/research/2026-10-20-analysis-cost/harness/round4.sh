#!/bin/bash
# Round 4 (21 Oct): Brain 4.0 one pass, cheap to premium, on the real calls and the fictional set.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PYB="nice -n 19 ionice -c3 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python"
RC_ROUND=4 $PYB realcalls.py text
RC_ROUND=4 $PYB realcalls.py judge
RC_PROVIDERS=anthropic $PYB realcalls.py judge          # Haiku on the round-3 arms
T=asr/openrouter_google_gemini-3.1-flash-lite/phone_8k
for m in openai/gpt-6-luna anthropic/claude-sonnet-5.5; do
  $PYB run.py text --shape brain4 --model $m --transcript $T
  D=../results/text/brain4/${m/\//_}/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1
  $PYB run.py judge --result $D --judge anthropic/claude-haiku-5.5
  $PYB run.py rjudge --result $D --judge anthropic/claude-haiku-5.5
done
for i in $(seq 1 240); do pgrep -f "harness/realcalls-luna.sh" > /dev/null || break; sleep 30; done
$PYB realcalls.py score > ../realcalls/scores.md
echo round4-finished
