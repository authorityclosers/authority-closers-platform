#!/usr/bin/env bash
# Nightly signed-in Sales Xray check on production (see nightly.mjs). Reads the QA
# account from its 0600 file without printing it; keeps 30 days of runs.
set -uo pipefail
cd /home/acdev/qa-nightly || exit 1
set -a
# shellcheck source=/dev/null
. /home/acdev/.config/ac-qa/production-account.env
set +a
export SX_FIXTURE=/home/acdev/src/dev-live/authority-closers-platform/packages/python/ac_platform/conversation_intelligence/canary_fixture/sales_call_v1.wav
export PATH=/home/acdev/.local/opt/node/bin:$PATH
# ac has no desktop libraries: Chrome's few missing ones are unpacked from Ubuntu's
# own packages into lib/ (apt-get download + dpkg-deb -x; nothing installed).
export LD_LIBRARY_PATH=/home/acdev/qa-nightly/lib
mkdir -p runs
find runs -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null
# The one analysis a night starts only once ANALYSIS_ENABLED exists: it is created
# when production runs the canary-by-source exclusion (workbench 9dacd869), so the
# QA call never counts as a real one. Until then: sign in and screens only.
[ -f ANALYSIS_ENABLED ] || export DRY=1
node nightly.mjs
