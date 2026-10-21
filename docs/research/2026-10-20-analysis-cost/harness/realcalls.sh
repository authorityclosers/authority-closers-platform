#!/bin/bash
# Round 3: real calls (owner-approved 21 Oct): approved providers only, zero data retention.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:. BENCH_STRICT=1 RC_PROVIDERS=${RC_PROVIDERS:-google}
PY="nice -n 19 ionice -c3 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python realcalls.py"
$PY asr && $PY text && $PY judge && $PY score > ../realcalls/scores.md
echo realcalls-finished
