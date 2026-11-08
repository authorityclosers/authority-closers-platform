#!/bin/sh
# One design capture run under the robot's slice (run as root): sh run-capture.sh <outfile> [engine capture args ...]
# QA_CAPTURES picks the folder (default /var/qa-captures). Its own state folder holds NO-OWNER, so the real owner alias stays blocked here too.
OUT="$1"; shift
DIR=/home/acdev/qa-engine
STATE=/var/tmp/qa-state-cap
sudo -u acdev sh -c "mkdir -p $STATE && touch $STATE/NO-OWNER"
: > "$OUT"
chmod 644 "$OUT"
systemd-run --quiet --wait --pipe --collect --slice=ac-strikes.slice \
  -p MemoryHigh=2400M -p MemoryMax=3200M -p CPUQuota=45% -p CPUWeight=20 -p Nice=15 -p IOSchedulingClass=idle \
  -p User=acdev -p WorkingDirectory="$DIR" -p Environment=HOME=/home/acdev -p Environment=QA_STATE=$STATE \
  -p Environment=QA_CAPTURES="${QA_CAPTURES:-/var/qa-captures}" -p Environment=LD_LIBRARY_PATH="$DIR/chromelibs" \
  /usr/local/bin/node "$DIR/engine.cjs" capture "$@" >> "$OUT" 2>&1
echo "=== done rc $?" >> "$OUT"
