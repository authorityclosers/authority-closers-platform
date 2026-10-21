#!/bin/bash
# Round 6 (21 Oct): measured pause statistics (ffmpeg, local) feed the Brain 4.0 one pass.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PYB="nice -n 19 ionice -c3 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python"
$PYB realcalls.py measure && RC_MODELS=openai/gpt-6-luna $PYB realcalls.py brain4m && RC_ROUND=6 $PYB realcalls.py judge
echo round6-finished
