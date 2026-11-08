#!/bin/sh
# One read-only script under the robot's caps (run as root): sh run-node.sh <script.cjs> <outfile> [VAR=value ...]
# Output goes to <outfile>, which ends with "=== done rc N". The browser libraries and the state folder are the robot's own.
SCRIPT="$1"; OUT="$2"; shift 2
DIR=/home/acdev/qa-engine
ENVS=""
for kv in "$@"; do ENVS="$ENVS -p Environment=$kv"; done
: > "$OUT"
chmod 644 "$OUT"
# shellcheck disable=SC2086
systemd-run --quiet --wait --pipe --collect --slice=ac-strikes.slice \
  -p MemoryHigh=2400M -p MemoryMax=3200M -p CPUQuota=60% -p CPUWeight=20 -p Nice=15 -p IOSchedulingClass=idle \
  -p User=acdev -p WorkingDirectory="$DIR" -p Environment=HOME=/home/acdev -p Environment=LD_LIBRARY_PATH="$DIR/chromelibs" $ENVS \
  /usr/local/bin/node "$SCRIPT" >> "$OUT" 2>&1
echo "=== done rc $?" >> "$OUT"
