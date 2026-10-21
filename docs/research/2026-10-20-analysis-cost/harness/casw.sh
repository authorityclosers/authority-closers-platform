#!/bin/bash
# compact transcript runs on the staging project's Gemini key (orchestrator, 21 Oct): usage casw.sh <style> <ids...>
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
nice -n 19 /home/acdev/research/analysis-cost-20261020/venv/bin/python compact_asr.py "$1" fictional "${@:2}"
