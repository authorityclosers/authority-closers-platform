#!/bin/bash
# Round 5 (21 Oct): delivery observations from the audio (Gemini 3.1 Flash-Lite) feed the Brain 4.0 one pass.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PYB="nice -n 19 ionice -c3 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python"
$PYB realcalls.py delivery && RC_MODELS=openai/gpt-6-luna $PYB realcalls.py brain4d && RC_ROUND=5 $PYB realcalls.py judge
echo round5-finished
