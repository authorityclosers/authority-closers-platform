#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_ACCOUNT_ID:?Set CLOUDFLARE_ACCOUNT_ID}"
: "${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN}"

command -v curl >/dev/null
command -v jq >/dev/null

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
repo_policy="$repo_root/config/r2/free-tier-policy.conf"
installed_policy='/srv/authority-closers/current/config/r2/free-tier-policy.conf'

if [[ -n "${R2_POLICY_FILE:-}" ]]; then
  policy_file="$R2_POLICY_FILE"
elif [[ -r "$repo_policy" ]]; then
  policy_file="$repo_policy"
else
  policy_file="$installed_policy"
fi

if [[ ! -r "$policy_file" ]]; then
  printf 'R2 policy is not readable: %s\n' "$policy_file" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$policy_file"

: "${R2_MAX_STANDARD_BYTES:?Missing R2_MAX_STANDARD_BYTES}"
: "${R2_MAX_CLASS_A_MONTH:?Missing R2_MAX_CLASS_A_MONTH}"
: "${R2_MAX_CLASS_B_MONTH:?Missing R2_MAX_CLASS_B_MONTH}"
: "${R2_FORBID_INFREQUENT_ACCESS:?Missing R2_FORBID_INFREQUENT_ACCESS}"

for value in \
  "$R2_MAX_STANDARD_BYTES" \
  "$R2_MAX_CLASS_A_MONTH" \
  "$R2_MAX_CLASS_B_MONTH" \
  "$R2_FORBID_INFREQUENT_ACCESS"; do
  [[ "$value" =~ ^[0-9]+$ ]] || {
    printf 'R2 policy values must be non-negative integers.\n' >&2
    exit 1
  }
done

auth_header="Authorization: Bearer $CLOUDFLARE_API_TOKEN"
api_base="https://api.cloudflare.com/client/v4"

storage_json="$(curl \
  --fail-with-body \
  --silent \
  --show-error \
  --retry 2 \
  --header "$auth_header" \
  "$api_base/accounts/$CLOUDFLARE_ACCOUNT_ID/r2/metrics")"

jq -e '.success == true and (.result | type == "object")' \
  <<<"$storage_json" >/dev/null

standard_bytes="$(jq -r '
  [
    (.result.standard.uploaded.payloadSize // 0),
    (.result.standard.uploaded.metadataSize // 0),
    (.result.standard.published.payloadSize // 0),
    (.result.standard.published.metadataSize // 0)
  ] | add
' <<<"$storage_json")"

infrequent_bytes="$(jq -r '
  [
    (.result.infrequentAccess.uploaded.payloadSize // 0),
    (.result.infrequentAccess.uploaded.metadataSize // 0),
    (.result.infrequentAccess.published.payloadSize // 0),
    (.result.infrequentAccess.published.metadataSize // 0)
  ] | add
' <<<"$storage_json")"

month_start="$(date -u +%Y-%m-01T00:00:00Z)"
month_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# GraphQL variable references are intentionally literal.
# shellcheck disable=SC2016
graphql_query='query R2Monthly($accountTag: string!, $startDate: Time!, $endDate: Time!) { viewer { accounts(filter: {accountTag: $accountTag}) { r2OperationsAdaptiveGroups(limit: 10000, filter: {datetime_geq: $startDate, datetime_leq: $endDate}) { sum { requests } dimensions { actionType } } } } }'

graphql_body="$(jq -n \
  --arg query "$graphql_query" \
  --arg accountTag "$CLOUDFLARE_ACCOUNT_ID" \
  --arg startDate "$month_start" \
  --arg endDate "$month_end" \
  '{query: $query, variables: {accountTag: $accountTag, startDate: $startDate, endDate: $endDate}}')"

operations_json="$(curl \
  --fail-with-body \
  --silent \
  --show-error \
  --retry 2 \
  --request POST \
  --header "$auth_header" \
  --header 'Content-Type: application/json' \
  --data "$graphql_body" \
  "$api_base/graphql")"

jq -e '(.errors // []) | length == 0' <<<"$operations_json" >/dev/null

class_a=0
class_b=0
unknown=0

while IFS=$'\t' read -r action requests; do
  [[ -n "$action" ]] || continue
  case "$action" in
    ListBuckets|PutBucket|CreateBucket|ListObjects|ListObjectsV2|PutObject|CopyObject|CompleteMultipartUpload|CreateMultipartUpload|LifecycleStorageTierTransition|ListMultipartUploads|UploadPart|UploadPartCopy|ListParts|PutBucketEncryption|PutBucketCors|PutBucketLifecycleConfiguration)
      class_a=$((class_a + requests))
      ;;
    HeadBucket|HeadObject|GetObject|UsageSummary|GetBucketEncryption|GetBucketLocation|GetBucketCors|GetBucketLifecycleConfiguration)
      class_b=$((class_b + requests))
      ;;
    DeleteObject|DeleteBucket|AbortMultipartUpload|LifecycleDeletion)
      ;;
    *)
      printf 'UNKNOWN  R2 operation type %s (%s requests).\n' "$action" "$requests" >&2
      unknown=$((unknown + requests))
      ;;
  esac
done < <(jq -r '
  (.data.viewer.accounts[0].r2OperationsAdaptiveGroups // [])[]
  | [.dimensions.actionType, (.sum.requests // 0)]
  | @tsv
' <<<"$operations_json")

failures=0

if ((standard_bytes > R2_MAX_STANDARD_BYTES)); then
  printf 'FAIL  Standard R2 bytes %s exceed policy ceiling %s.\n' \
    "$standard_bytes" "$R2_MAX_STANDARD_BYTES" >&2
  failures=$((failures + 1))
fi

if ((R2_FORBID_INFREQUENT_ACCESS == 1 && infrequent_bytes > 0)); then
  printf 'FAIL  Infrequent Access usage is forbidden but %s bytes exist.\n' \
    "$infrequent_bytes" >&2
  failures=$((failures + 1))
fi

if ((class_a > R2_MAX_CLASS_A_MONTH)); then
  printf 'FAIL  Class A operations %s exceed policy ceiling %s.\n' \
    "$class_a" "$R2_MAX_CLASS_A_MONTH" >&2
  failures=$((failures + 1))
fi

if ((class_b > R2_MAX_CLASS_B_MONTH)); then
  printf 'FAIL  Class B operations %s exceed policy ceiling %s.\n' \
    "$class_b" "$R2_MAX_CLASS_B_MONTH" >&2
  failures=$((failures + 1))
fi

if ((unknown > 0)); then
  printf 'FAIL  Unknown R2 operations prevent a safe cost classification.\n' >&2
  failures=$((failures + 1))
fi

printf 'R2 usage: standard_bytes=%s infrequent_bytes=%s class_a=%s class_b=%s\n' \
  "$standard_bytes" "$infrequent_bytes" "$class_a" "$class_b"

if ((failures > 0)); then
  exit 1
fi

printf 'PASS  R2 usage is inside the conservative free-tier operating envelope.\n'
