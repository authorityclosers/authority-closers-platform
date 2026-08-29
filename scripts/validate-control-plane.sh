#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

shell_files=()
while IFS= read -r -d '' candidate; do
  if head -n 1 "$candidate" | grep -Eq '^#!.*(ba)?sh([[:space:]]|$)'; then
    shell_files+=("$candidate")
  fi
done < <(find . -path './.git' -prune -o -type f -print0)
if ((${#shell_files[@]} > 0)); then
  bash -n "${shell_files[@]}"
  shellcheck "${shell_files[@]}"
fi

if git grep -Il $'\r' -- '*.sh' '*.service' '*.timer' '*.yml' '*.yaml'; then
  printf 'CRLF detected in a Linux operational file.\n' >&2
  exit 1
fi

if git grep -nEI \
  '(BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|cfat_[A-Za-z0-9_-]{20,}|re_[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})' \
  -- . ':!.github/workflows/control-plane.yml' ':!scripts/validate-control-plane.sh'; then
  printf 'Possible committed credential detected.\n' >&2
  exit 1
fi

if [[ -x infra/vps-foundation/scripts/validate-images-pinned.sh ]]; then
  CADDY_IMAGE="caddy@sha256:$(printf '0%.0s' {1..64})" \
  OTEL_IMAGE="otel/opentelemetry-collector-contrib@sha256:$(printf '1%.0s' {1..64})" \
    infra/vps-foundation/scripts/validate-images-pinned.sh
fi

printf 'PASS  Control-plane validation completed.\n'
