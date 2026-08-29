#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
evaluator="$repo_root/infra/vps-foundation/scripts/r2-usage-evaluate.sh"
fixtures="$repo_root/tests/infra/fixtures/r2"
policy="$repo_root/infra/vps-foundation/config/r2/free-tier-policy.conf"

expect_pass() {
  local storage="$1"
  local operations="$2"
  "$evaluator" "$fixtures/$storage" "$fixtures/$operations" "$policy" >/dev/null
}

expect_fail() {
  local storage="$1"
  local operations="$2"
  if "$evaluator" "$fixtures/$storage" "$fixtures/$operations" "$policy" >/dev/null 2>&1; then
    printf 'Expected R2 fixture evaluation to fail: %s %s\n' "$storage" "$operations" >&2
    exit 1
  fi
}

expect_pass storage-valid.json operations-valid-zero.json
usage_output="$($evaluator "$fixtures/storage-valid.json" "$fixtures/operations-valid-usage.json" "$policy")"
grep -q 'standard_bytes=330 infrequent_bytes=0 class_a=7 class_b=11' <<<"$usage_output"

expect_fail storage-missing-field.json operations-valid-zero.json
expect_fail storage-valid.json operations-empty-accounts.json
expect_fail storage-valid.json operations-missing-dataset.json
expect_fail storage-valid.json operations-unknown-action.json
expect_fail storage-valid.json operations-malformed-count.json

tmp_dir="$(mktemp -d -t ac-r2-policy-test.XXXXXX)"
cleanup() { rm -rf -- "$tmp_dir"; }
trap cleanup EXIT
marker="$tmp_dir/should-not-exist"
printf '%s\n' \
  'R2_MAX_STANDARD_BYTES=1' \
  'R2_MAX_CLASS_A_MONTH=1' \
  'R2_MAX_CLASS_B_MONTH=1' \
  'R2_FORBID_INFREQUENT_ACCESS=1' \
  "UNEXPECTED_POLICY_KEY=\$(touch \"$marker\")" \
  > "$tmp_dir/unsafe-policy.conf"
if "$evaluator" "$fixtures/storage-valid.json" "$fixtures/operations-valid-zero.json" "$tmp_dir/unsafe-policy.conf" >/dev/null 2>&1; then
  printf 'Expected unknown R2 policy assignment to fail.\n' >&2
  exit 1
fi
[[ ! -e "$marker" ]]

printf 'PASS  R2 usage evaluator fails closed for missing, malformed, ambiguous, and unknown metrics.\n'
