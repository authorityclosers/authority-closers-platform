#!/usr/bin/env bash
set -u

: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is required}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"

tmp_file="$(mktemp -t ac-r2-metrics-diagnostic.XXXXXX)"
trap 'rm -f -- "$tmp_file"' EXIT

status="$(curl --silent --show-error --max-time 20 \
  --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  --output "$tmp_file" \
  --write-out '%{http_code}' \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/r2/metrics")"
printf 'REST_STATUS=%s\n' "$status"
if [[ "$status" != '200' ]]; then
  jq -c '{success,errors,messages}' "$tmp_file" 2>/dev/null || true
  exit 1
fi
printf 'REST_RESPONSE_OK=true\n'

month_start="$(date -u +%Y-%m-01T00:00:00Z)"
month_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Dollar-prefixed names are GraphQL variables, not shell expansions.
# shellcheck disable=SC2016
graphql_query='query R2Monthly($accountTag: string!, $startDate: Time!, $endDate: Time!) { viewer { accounts(filter: {accountTag: $accountTag}) { r2OperationsAdaptiveGroups(limit: 10000, filter: {datetime_geq: $startDate, datetime_leq: $endDate}) { sum { requests } dimensions { actionType } } } } }'
graphql_body="$(jq -n \
  --arg query "$graphql_query" \
  --arg accountTag "$CLOUDFLARE_ACCOUNT_ID" \
  --arg startDate "$month_start" \
  --arg endDate "$month_end" \
  '{query: $query, variables: {accountTag: $accountTag, startDate: $startDate, endDate: $endDate}}')"

status="$(curl --silent --show-error --max-time 20 \
  --request POST \
  --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  --header 'Content-Type: application/json' \
  --data "$graphql_body" \
  --output "$tmp_file" \
  --write-out '%{http_code}' \
  'https://api.cloudflare.com/client/v4/graphql')"
printf 'GRAPHQL_STATUS=%s\n' "$status"
jq -c '{errors,messages,data_present:(.data != null)}' "$tmp_file" 2>/dev/null || true
[[ "$status" == '200' ]] || exit 1
jq -e '(.errors // []) | length == 0' "$tmp_file" >/dev/null || exit 1
printf 'GRAPHQL_RESPONSE_OK=true\n'
