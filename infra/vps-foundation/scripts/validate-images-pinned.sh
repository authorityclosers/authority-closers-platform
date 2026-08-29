#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repo_root/compose/foundation/compose.yaml"
image_env_file="${AC_FOUNDATION_IMAGE_ENV_FILE:-$repo_root/config/release/foundation-images.env}"

[[ -r "$image_env_file" ]] || {
  printf 'FAIL  Approved image manifest is not readable: %s\n' "$image_env_file" >&2
  exit 1
}

mapfile -t images < <(docker compose --env-file "$image_env_file" -f "$compose_file" config --images)
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

printf 'PASS  All Compose images are committed and digest-pinned in %s.\n' "$image_env_file"
