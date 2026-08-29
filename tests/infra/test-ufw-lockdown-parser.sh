#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
parser="$repo_root/infra/vps-foundation/scripts/parse-ufw-ssh-rules.sh"
fixtures="$repo_root/tests/infra/fixtures"

ipv4_result="$(bash "$parser" < "$fixtures/ufw-status-numbered-ipv4.txt")"
[[ "$ipv4_result" == $'3\n1' ]] || {
  printf 'Unexpected IPv4 SSH rule parse result:\n%s\n' "$ipv4_result" >&2
  exit 1
}

ipv6_result="$(bash "$parser" < "$fixtures/ufw-status-numbered-ipv6.txt")"
[[ "$ipv6_result" == $'7\n6' ]] || {
  printf 'Unexpected IPv6 SSH rule parse result:\n%s\n' "$ipv6_result" >&2
  exit 1
}

printf 'PASS  UFW lockdown parser handles standard IPv4 and IPv6 numbered rules.\n'
