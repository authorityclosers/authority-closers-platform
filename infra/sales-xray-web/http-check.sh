#!/bin/sh
set -eu

url=$1
mode=${2:-http}
case "$mode" in
  api) set -- --header "Host: ${AC_API_HOST:?AC_API_HOST is required}" ;;
  http|sales-xray) set -- ;;
  *) exit 2 ;;
esac
if [ "$mode" = sales-xray ]; then
  set -- "$@" --output -
else
  set -- "$@" --output /dev/null
fi

# Keep GET and redirect handling, and require a final 2xx (not merely <400).
# Disable curlrc and proxies so this probe always uses the container listener.
response=$(curl --disable --noproxy '*' --fail --silent --show-error \
  --location --max-time 3 --write-out '\n%{http_code}' "$@" "$url") || exit 1
newline='
'
case "${response##*"$newline"}" in
  2??) ;;
  *) exit 1 ;;
esac

if [ "$mode" = sales-xray ]; then
  printf '%s' "${response%"$newline"*}" | jq --exit-status --slurp \
    --arg release "${AC_RELEASE_ID:?AC_RELEASE_ID is required}" \
    'length == 1 and (.[0] | .status == "ok" and .service == "sales-xray-web"
      and .release_id == $release)' >/dev/null
fi
