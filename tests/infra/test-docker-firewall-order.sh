#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
validator="$repo_root/infra/vps-foundation/scripts/ac-docker-firewall-validate"
fixtures="$repo_root/tests/infra/fixtures"

"$validator" eth0 < "$fixtures/docker-user-valid.txt" >/dev/null
if "$validator" eth0 < "$fixtures/docker-user-return-before-drop.txt" >/dev/null 2>&1; then
  printf 'Firewall validator accepted a DROP after Docker RETURN.\n' >&2
  exit 1
fi
if "$validator" eth0 < "$fixtures/docker-user-duplicate-drop.txt" >/dev/null 2>&1; then
  printf 'Firewall validator accepted duplicate managed DROP rules.\n' >&2
  exit 1
fi

printf 'PASS  Docker ingress rules must be first and second in DOCKER-USER.\n'
