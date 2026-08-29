#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
foundation="$repo_root/infra/vps-foundation"
policy="$foundation/config/release/os-baseline.env"
packages="$foundation/config/release/os-packages.tsv"
bootstrap="$foundation/scripts/bootstrap-host.sh"

grep -Eq '^AC_OS_BASELINE_ID=[a-z0-9][a-z0-9.-]{7,127}$' "$policy"
grep -Eq '^DOCKER_APT_KEY_SHA256=[0-9a-f]{64}$' "$policy"
grep -Eq '^CLOUDFLARE_APT_KEY_SHA256=[0-9a-f]{64}$' "$policy"

awk -F '\t' '
  /^#/ || NF == 0 { next }
  NF != 2 { exit 1 }
  $1 !~ /^[a-z0-9][a-z0-9+.-]*$/ { exit 1 }
  $2 !~ /^[A-Za-z0-9.+:~_-]+$/ { exit 1 }
  seen[$1]++ { exit 1 }
  END { if (length(seen) < 20) exit 1 }
' "$packages"

if grep -Eq 'dist-upgrade|apt-get install -y docker-ce|apt-get install -y cloudflared' "$bootstrap"; then
  printf 'Bootstrap bypasses the separately versioned package baseline.\n' >&2
  exit 1
fi
grep -q 'install-os-baseline.sh' "$bootstrap"
grep -q 'ac-os-baseline-verify' "$bootstrap"

printf 'PASS  OS package mutation is pinned and gated by a separately versioned baseline.\n'
