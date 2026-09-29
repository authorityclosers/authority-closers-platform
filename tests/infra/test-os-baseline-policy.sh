#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
foundation="$repo_root/infra/vps-foundation"
policy="$foundation/config/release/os-baseline.env"
packages="$foundation/config/release/os-packages.tsv"
resolved_packages="$foundation/config/release/os-resolved-packages.tsv"
bootstrap="$foundation/scripts/bootstrap-host.sh"

grep -Eq '^AC_OS_BASELINE_ID=[a-z0-9][a-z0-9.-]{7,127}$' "$policy"
grep -Eq '^DOCKER_APT_KEY_SHA256=[0-9a-f]{64}$' "$policy"
grep -Eq '^CLOUDFLARE_APT_KEY_SHA256=[0-9a-f]{64}$' "$policy"
resolved_packages_sha="$(awk -F= '$1 == "AC_OS_RESOLVED_PACKAGES_SHA256" {print $2}' "$policy")"
[[ "$resolved_packages_sha" == "$(sha256sum "$resolved_packages" | awk '{print $1}')" ]]

baseline_fixtures="$repo_root/tests/infra/fixtures/os-baseline"
base_resolved_fixture="$baseline_fixtures/ubuntu-noble-amd64-2026-08-30-v1.tsv"
ffmpeg_delta_fixture="$baseline_fixtures/ubuntu-noble-amd64-2026-09-28-v1-ffmpeg.tsv"
# Security updates that replaced a pinned version after its old version left the Ubuntu archive.
updates_fixture="$baseline_fixtures/ubuntu-noble-amd64-2026-09-29-v1-updates.tsv"
expected_resolved="$(mktemp)"
trap 'rm -f -- "$expected_resolved"' EXIT
base_resolved_sha="$(sha256sum "$base_resolved_fixture" | awk '{print $1}')"
[[ "$base_resolved_sha" == '1f43279b601f915f6fefe54a673c920dc11473db267068eb25168b09a15ae96c' ]]
[[ "$(wc -l < "$ffmpeg_delta_fixture" | tr -d ' ')" == 163 ]]
ffmpeg_policy_version="$(awk -F '\t' '$1 == "ffmpeg" {print $2}' "$packages")"
ffmpeg_delta_version="$(awk -F '\t' '$1 == "ffmpeg" {print $2}' "$ffmpeg_delta_fixture")"
[[ -n "$ffmpeg_policy_version" && "$ffmpeg_policy_version" == "$ffmpeg_delta_version" ]]
grep -Fxq 'AC_OS_BASELINE_ID=ubuntu-noble-amd64-2026-09-29-v1' "$policy"
[[ "$(wc -l < "$updates_fixture" | tr -d ' ')" == 1 ]]
# Each update replaces the version of a package already in the list; it never adds one.
cat "$base_resolved_fixture" "$ffmpeg_delta_fixture" | awk -F '\t' '
  NR == FNR { update[$1] = $2; next }
  $1 in update { print $1 "\t" update[$1]; replaced[$1] = 1; next }
  { print }
  END { for (package in update) if (!(package in replaced)) exit 1 }
' "$updates_fixture" - | LC_ALL=C sort > "$expected_resolved"
if ! cmp -s "$expected_resolved" "$resolved_packages"; then
  diff -u "$expected_resolved" "$resolved_packages" >&2
  exit 1
fi

awk -F '\t' '
  /^#/ || NF == 0 { next }
  NF != 2 { exit 1 }
  $1 !~ /^[a-z0-9][a-z0-9+.-]*$/ { exit 1 }
  $2 !~ /^[A-Za-z0-9.+:~_-]+$/ { exit 1 }
  seen[$1]++ { exit 1 }
  END { if (length(seen) < 20) exit 1 }
' "$packages"

awk -F '\t' '
  NF != 2 { exit 1 }
  $1 !~ /^[a-z0-9][a-z0-9+.-]*(:[a-z0-9-]+)?$/ { exit 1 }
  length($2) == 0 { exit 1 }
  seen[$1]++ { exit 1 }
  END { if (length(seen) < 100) exit 1 }
' "$resolved_packages"

if grep -Eq 'dist-upgrade|apt-get install -y docker-ce|apt-get install -y cloudflared' "$bootstrap"; then
  printf 'Bootstrap bypasses the separately versioned package baseline.\n' >&2
  exit 1
fi
grep -q 'install-os-baseline.sh' "$bootstrap"
grep -q 'ac-os-baseline-verify' "$bootstrap"
grep -q 'Current installed package set differs from recorded baseline' \
  "$foundation/scripts/ac-os-baseline-verify"
grep -q 'Resolved package graph differs from the committed baseline manifest' \
  "$foundation/scripts/install-os-baseline.sh"
# shellcheck disable=SC2016  # This static assertion intentionally matches a literal array reference.
grep -q 'apt-mark hold "${resolved_packages\[@\]}"' \
  "$foundation/scripts/install-os-baseline.sh"
grep -q 'unhold_managed_packages' "$foundation/scripts/install-os-baseline.sh"
grep -q 'restore_managed_hold_state' "$foundation/scripts/install-os-baseline.sh"
grep -q 'ac_os_baseline_failure_disposition' "$foundation/scripts/install-os-baseline.sh"
grep -q 'os-baseline-recovery-required.env' "$foundation/scripts/install-os-baseline.sh"
grep -q 'hold_transition_committed=1' "$foundation/scripts/install-os-baseline.sh"

printf 'PASS  OS package mutation is pinned and gated by a separately versioned baseline.\n'
