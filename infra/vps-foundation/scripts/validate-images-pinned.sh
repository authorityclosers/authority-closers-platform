#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repo_root/compose/foundation/compose.yaml"

mapfile -t images < <(docker compose -f "$compose_file" config --images)
((${#images[@]} > 0)) || {
  printf 'FAIL  Compose did not resolve any images.\n' >&2
  exit 1
}

for image in "${images[@]}"; do
  if [[ ! "$image" =~ @sha256:[0-9a-f]{64}$ ]]; then
    printf 'FAIL  Mutable or invalid image reference: %s\n' "$image" >&2
    exit 1
  fi
done

printf 'PASS  All Compose images are digest-pinned.\n'
