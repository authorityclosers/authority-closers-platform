#!/usr/bin/env bash
# The 15-minute production monitor (see monitor.mjs). Reads the QA account from its 0600 file without printing
# it; the monitor itself only reads production.
set -uo pipefail
cd /home/acdev/qa-monitor || exit 1
set -a
# shellcheck source=/dev/null
. /home/acdev/.config/ac-qa/production-account.env
set +a
export PATH=/home/acdev/.local/opt/node/bin:$PATH
# ac has no desktop libraries: Chrome's few missing ones are the nightly's unpacked copies (nothing installed).
export LD_LIBRARY_PATH=/home/acdev/qa-nightly/lib
exec node scripts/qa/monitor/monitor.mjs
