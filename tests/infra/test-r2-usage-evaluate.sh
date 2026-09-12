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

tmp_dir="$(mktemp -d -t ac-r2-policy-test.XXXXXX)"
cleanup() { rm -rf -- "$tmp_dir"; }
trap cleanup EXIT

write_storage_fixture() {
  local standard_value="$1"
  local infrequent_value="${2:-0}"
  printf '{
  "success": true,
  "result": {
    "standard": {
      "uploaded": {"payloadSize": %s, "metadataSize": 0},
      "published": {"payloadSize": 0, "metadataSize": 0}
    },
    "infrequentAccess": {
      "uploaded": {"payloadSize": %s, "metadataSize": 0},
      "published": {"payloadSize": 0, "metadataSize": 0}
    }
  }
}
' "$standard_value" "$infrequent_value" > "$tmp_dir/storage.json"
}

write_operations_fixture() {
  local action="$1"
  local requests="$2"
  printf '{
  "data": {
    "viewer": {
      "accounts": [{
        "r2OperationsAdaptiveGroups": [
          {"dimensions": {"actionType": "%s"}, "sum": {"requests": %s}}
        ]
      }]
    }
  }
}
' "$action" "$requests" > "$tmp_dir/operations.json"
}

expect_generated_pass() {
  if ! "$evaluator" "$tmp_dir/storage.json" "$tmp_dir/operations.json" "$policy" >/dev/null; then
    printf 'Expected generated R2 fixture evaluation to pass.\n' >&2
    exit 1
  fi
}

expect_generated_fail() {
  if "$evaluator" "$tmp_dir/storage.json" "$tmp_dir/operations.json" "$policy" >/dev/null 2>&1; then
    printf 'Expected generated R2 fixture evaluation to fail.\n' >&2
    exit 1
  fi
}

expect_pass storage-valid.json operations-valid-zero.json
usage_output="$($evaluator "$fixtures/storage-valid.json" "$fixtures/operations-valid-usage.json" "$policy")"
grep -q 'standard_bytes=330 infrequent_bytes=0 class_a=7 class_b=11' <<<"$usage_output"
R2_PROJECTED_ADDITIONAL_BYTES=8589934262 \
  "$evaluator" "$fixtures/storage-valid.json" "$fixtures/operations-valid-zero.json" "$policy" >/dev/null
if R2_PROJECTED_ADDITIONAL_BYTES=8589934263 \
  "$evaluator" "$fixtures/storage-valid.json" "$fixtures/operations-valid-zero.json" "$policy" >/dev/null 2>&1; then
  printf 'Expected projected R2 storage above the envelope to fail.\n' >&2
  exit 1
fi

# The storage bound is unchanged: equality is valid, one byte above is not.
write_storage_fixture 8589934592
write_operations_fixture PutObject 0
expect_generated_pass
write_storage_fixture 8589934593
expect_generated_fail

write_storage_fixture 0
write_operations_fixture PutObject 699999
expect_generated_pass
write_operations_fixture PutObject 700000
expect_generated_fail
write_operations_fixture PutObject 700001
expect_generated_fail
write_operations_fixture GetObject 6999999
expect_generated_pass
write_operations_fixture GetObject 7000000
expect_generated_fail
write_operations_fixture GetObject 7000001
expect_generated_fail

# Values above signed 64-bit must fail closed rather than wrap. The projection
# case specifically regresses the old Bash addition overflow path.
write_storage_fixture 9223372036854775808
write_operations_fixture PutObject 0
expect_generated_fail
write_storage_fixture 0
if R2_PROJECTED_ADDITIONAL_BYTES=18446744073709551615 \
  "$evaluator" "$tmp_dir/storage.json" "$tmp_dir/operations.json" "$policy" >/dev/null 2>&1; then
  printf 'Expected overflowing projected R2 storage to fail.\n' >&2
  exit 1
fi
write_operations_fixture PutObject 9223372036854775808
expect_generated_fail
write_operations_fixture GetObject 9223372036854775808
expect_generated_fail
write_operations_fixture FutureBillableOperation 9223372036854775808
expect_generated_fail

# Decimal parsing is bounded, so an unreasonably long value is rejected
# before jq/Bash arithmetic can turn it into an unsafe number.
huge_decimal="$(printf '9%.0s' {1..4097})"
write_storage_fixture 0
write_operations_fixture PutObject 0
if R2_PROJECTED_ADDITIONAL_BYTES="$huge_decimal" \
  "$evaluator" "$tmp_dir/storage.json" "$tmp_dir/operations.json" "$policy" >/dev/null 2>&1; then
  printf 'Expected overlong R2 projection to fail closed.\n' >&2
  exit 1
fi

expect_fail storage-missing-field.json operations-valid-zero.json
expect_fail storage-valid.json operations-empty-accounts.json
expect_fail storage-valid.json operations-missing-dataset.json
expect_fail storage-valid.json operations-unknown-action.json
expect_fail storage-valid.json operations-malformed-count.json

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
