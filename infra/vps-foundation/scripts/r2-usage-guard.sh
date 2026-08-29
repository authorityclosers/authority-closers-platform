#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_ACCOUNT_ID:?Set CLOUDFLARE_ACCOUNT_ID}"
: "${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN}"

[[ "$CLOUDFLARE_ACCOUNT_ID" =~ ^[A-Fa-f0-9]{32}$ ]] || {
  printf 'CLOUDFLARE_ACCOUNT_ID has an invalid shape.\n' >&2
  exit 1
}
[[ "$CLOUDFLARE_API_TOKEN" =~ ^[A-Za-z0-9_-]{20,}$ ]] || {
  printf 'CLOUDFLARE_API_TOKEN has an invalid shape.\n' >&2
  exit 1
}
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

[[ -r "$policy_file" ]] || {
  printf 'R2 policy is not readable: %s\n' "$policy_file" >&2
  exit 1
}

work_dir="$(mktemp -d -t ac-r2-usage.XXXXXX)"
cleanup() { rm -rf -- "$work_dir"; }
trap cleanup EXIT
storage_file="$work_dir/storage.json"
operations_file="$work_dir/operations.json"
graphql_body_file="$work_dir/graphql-body.json"
api_base='https://api.cloudflare.com/client/v4'

# The authorization header enters curl through stdin rather than argv.
printf 'header = "Authorization: Bearer %s"\n' "$CLOUDFLARE_API_TOKEN" \
  | curl --config - \
      --fail-with-body \
      --silent \
      --show-error \
      --retry 2 \
      --output "$storage_file" \
      "$api_base/accounts/$CLOUDFLARE_ACCOUNT_ID/r2/metrics"

month_start="$(date -u +%Y-%m-01T00:00:00Z)"
month_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# GraphQL variables are intentionally literal and populated in the JSON body.
# shellcheck disable=SC2016
graphql_query='query R2Monthly($accountTag: string!, $startDate: Time!, $endDate: Time!) { viewer { accounts(filter: {accountTag: $accountTag}) { r2OperationsAdaptiveGroups(limit: 10000, filter: {datetime_geq: $startDate, datetime_leq: $endDate}) { sum { requests } dimensions { actionType } } } } }'

jq --null-input \
  --arg query "$graphql_query" \
  --arg accountTag "$CLOUDFLARE_ACCOUNT_ID" \
  --arg startDate "$month_start" \
  --arg endDate "$month_end" \
  '{query: $query, variables: {accountTag: $accountTag, startDate: $startDate, endDate: $endDate}}' \
  > "$graphql_body_file"

printf 'header = "Authorization: Bearer %s"\n' "$CLOUDFLARE_API_TOKEN" \
  | curl --config - \
      --fail-with-body \
      --silent \
      --show-error \
      --retry 2 \
      --request POST \
      --header 'Content-Type: application/json' \
      --data-binary "@$graphql_body_file" \
      --output "$operations_file" \
      "$api_base/graphql"

"$script_dir/r2-usage-evaluate.sh" "$storage_file" "$operations_file" "$policy_file"
