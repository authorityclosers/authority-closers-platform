#!/bin/bash
# Refresh every score table, the leaderboard, cost fits and both bootstraps (CPU-light, nice'd).
set -e
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
SPY="nice -n 19 ionice -c3 ../venv/bin/python"
for w in asr retain facts report consistency cost; do $SPY score.py $w > ../results/scores/$w.md 2> ../logs/final_$w.err || echo "score $w failed"; done
$SPY summary.py > ../logs/final_summary.log 2>&1
$SPY fits.py > ../results/scores/fits.md 2>&1
$SPY boot.py > ../logs/final_boot.log 2>&1
echo done
