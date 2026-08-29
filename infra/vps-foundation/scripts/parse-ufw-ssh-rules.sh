#!/usr/bin/env bash
set -euo pipefail

# Read `ufw status numbered` from stdin and return public SSH ALLOW rule
# numbers in descending order so deletions do not renumber later matches.
awk '
  /(22\/tcp|OpenSSH)/ && /ALLOW[[:space:]]+IN/ {
    line = $0
    sub(/^\[[[:space:]]*/, "", line)
    if (match(line, /^[0-9]+/)) {
      print substr(line, RSTART, RLENGTH)
    }
  }
' | LC_ALL=C sort -rnu
