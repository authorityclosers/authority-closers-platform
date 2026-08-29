#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=infra/vps-foundation/scripts/lib/os-baseline-transaction.sh
. "$repo_root/infra/vps-foundation/scripts/lib/os-baseline-transaction.sh"

work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT

printf 'a\t1\nb\t2\n' > "$work_dir/rollback.tsv"
cp -- "$work_dir/rollback.tsv" "$work_dir/live-same.tsv"
printf 'a\t1\nb\t3\n' > "$work_dir/live-mixed.tsv"

[[ "$(ac_os_baseline_failure_disposition \
  "$work_dir/rollback.tsv" "$work_dir/live-same.tsv")" == 'rollback-safe' ]]
[[ "$(ac_os_baseline_failure_disposition \
  "$work_dir/rollback.tsv" "$work_dir/live-mixed.tsv")" == 'recovery-required' ]]

installer="$repo_root/infra/vps-foundation/scripts/install-os-baseline.sh"
grep -q 'clear_active_baseline_metadata' "$installer"
grep -q 'record_recovery_required' "$installer"
grep -q 'freeze_managed_package_graph' "$installer"
grep -q 'Existing OS baseline marker does not match the complete live package graph' "$installer"

printf 'PASS  OS baseline rollback metadata requires an exact live-graph match.\n'
