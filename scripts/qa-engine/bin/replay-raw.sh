#!/bin/sh
# One attack family as a dry run (nothing filed), whole verbose output kept (run as root).
# Usage: sh replay-raw.sh <outfile> <family> <page> <size> <alias>
OUT="$1"; FAMILY="$2"; PAGE="$3"; SIZE="$4"; ALIAS="$5"
DIR=/home/acdev/qa-engine
STATE=/var/tmp/qa-state-dry
sudo -u acdev sh -c "mkdir -p $STATE && touch $STATE/NO-OWNER"
: > "$OUT"
systemd-run --quiet --wait --pipe --collect --slice=ac-strikes.slice \
  -p MemoryHigh=2400M -p MemoryMax=3200M -p CPUQuota=60% -p CPUWeight=20 -p Nice=15 -p IOSchedulingClass=idle \
  -p User=acdev -p WorkingDirectory="$DIR" -p Environment=HOME=/home/acdev -p Environment=QA_STATE=$STATE \
  -p Environment=LD_LIBRARY_PATH="$DIR/chromelibs" -p Environment=QA_ATTACK_ALIAS="$ALIAS" \
  /usr/local/bin/node "$DIR/engine.cjs" attack --dry --verbose --family "$FAMILY" --page "$PAGE" --size "$SIZE" >> "$OUT" 2>&1
echo "=== done rc $?" >> "$OUT"
