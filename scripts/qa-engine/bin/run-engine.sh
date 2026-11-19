#!/bin/sh
# Start another engine command (sweep, rejudge, ...) in ac-strikes.slice, capped (run as root): sh run-engine.sh <command> [flags]
# The mixed run is its own unit now: systemctl start|stop|status qa-engine-mixed. The unit name here is qa-engine-<first word>;
# logs go to state/<unit>.log. The engine itself waits for a release cut, memory/CPU pressure and a PAUSE file.
set -eu
DIR=/home/acdev/qa-engine
UNIT="qa-engine-$1"
systemctl reset-failed "$UNIT" 2>/dev/null || true
exec systemd-run --quiet --unit="$UNIT" --slice=ac-strikes.slice --collect \
  -p MemoryHigh=2400M -p MemoryMax=3200M -p CPUQuota=60% -p CPUWeight=20 -p Nice=15 -p IOSchedulingClass=idle \
  -p User=acdev -p WorkingDirectory="$DIR" -p Environment=HOME=/home/acdev -p Environment=LD_LIBRARY_PATH="$DIR/chromelibs" \
  -p StandardOutput="append:$DIR/state/$UNIT.log" -p StandardError="append:$DIR/state/$UNIT.log" \
  /usr/local/bin/node "$DIR/engine.cjs" "$@"
