#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
D=../results/asr/sarvam_saaras-v4/phone_8k/retain/anthropic_claude-haiku-5.5
for f in $D/fx-*.json; do python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if 'error' in d else 1)" $f && { echo "retry $f"; rm $f; }; done
/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python run.py retain --result ../results/asr/sarvam_saaras-v4/phone_8k --judge anthropic/claude-haiku-5.5
/home/acdev/research/analysis-cost-20261020/venv/bin/python score.py retain > ../results/scores/retain.md
