#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
foundation="$repo_root/infra/vps-foundation"

if grep -REn -- '--token=|--client-secret=' \
  "$foundation/scripts/ac-infisical-run" \
  "$foundation/scripts/ac-infisical-run-backup"; then
  printf 'Infisical credential or token is exposed through argv.\n' >&2
  exit 1
fi
grep -q 'export INFISICAL_TOKEN=' "$foundation/scripts/ac-infisical-run"
grep -q 'export INFISICAL_TOKEN=' "$foundation/scripts/ac-infisical-run-backup"

if grep -Eq '\[Parameter\(Mandatory = \$true\)\].*(ApiToken|ApiKey)' \
  "$foundation/scripts/configure-cloudflare.ps1" \
  "$foundation/scripts/configure-resend-domain.ps1"; then
  printf 'Provider credential remains a PowerShell command-line parameter.\n' >&2
  exit 1
fi

grep -q 'DOCKER-USER chain is unavailable' "$foundation/scripts/ac-docker-firewall"
grep -q 'ip6tables' "$foundation/scripts/validate-foundation.sh"
grep -q 'IPV6=yes' "$foundation/scripts/validate-foundation.sh"
grep -q 'ufw status numbered' "$foundation/scripts/bootstrap-host.sh"

if grep -n 'tar .*|| true' "$foundation/scripts/bootstrap-host.sh"; then
  printf 'Rollback archive creation still suppresses tar failures.\n' >&2
  exit 1
fi

if find "$foundation/.github" -type f 2>/dev/null | grep -q .; then
  printf 'Nested GitHub workflows are inert and prohibited; checks belong at repository root.\n' >&2
  exit 1
fi

grep -Eq '^CADDY_IMAGE=.*@sha256:[0-9a-f]{64}$' "$foundation/config/release/foundation-images.env"
grep -Eq '^OTEL_IMAGE=.*@sha256:[0-9a-f]{64}$' "$foundation/config/release/foundation-images.env"
grep -Eq '^INFISICAL_LINUX_AMD64_SHA256=[0-9a-f]{64}$' "$foundation/config/release/toolchain.env"
grep -Eq '^RCLONE_LINUX_AMD64_SHA256=[0-9a-f]{64}$' "$foundation/config/release/toolchain.env"

printf 'PASS  Foundation security invariants are represented in executable controls.\n'
