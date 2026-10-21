#!/bin/bash
# fictional-set worker for the Brain 4.0 pass: usage fic4.sh <model> [reverse]
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
nice -n 19 /home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python - "$@" <<'PY'
import argparse, sys
import run as R
calls = R.call_ids(argparse.Namespace(calls=None))
if sys.argv[2:3] == ["reverse"]:
    calls = calls[::-1]
R.cmd_text(argparse.Namespace(shape="brain4", model=sys.argv[1], transcript="asr/openrouter_google_gemini-3.1-flash-lite/phone_8k",
                              run=1, calls=calls, force=False))
PY
