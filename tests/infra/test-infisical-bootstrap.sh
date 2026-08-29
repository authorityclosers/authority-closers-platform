#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
script="$repo_root/infra/vps-foundation/scripts/ac-create-infisical-bootstrap"
tmp_dir="$(mktemp -d -t ac-infisical-bootstrap-test.XXXXXX)"
cleanup() {
  local status=$?
  case "$tmp_dir" in
    /tmp/ac-infisical-bootstrap-test.*) rm -rf -- "$tmp_dir" ;;
    *) printf 'Refusing to remove unexpected test path: %s\n' "$tmp_dir" >&2; status=1 ;;
  esac
  exit "$status"
}
trap cleanup EXIT

source_file="$tmp_dir/production.env"
target_file="$tmp_dir/secrets/infisical-bootstrap.env"
sentinel="$tmp_dir/must-not-exist"
{
  printf 'INFISICAL_VPS_CLIENT_ID=client id with spaces\n'
  printf 'INFISICAL_VPS_CLIENT_SECRET=$(touch %s)\n' "$sentinel"
  printf 'INFISICAL_BACKUP_CLIENT_ID=back`tick; dollar $HOME and #hash\n'
  printf '%s\n' 'INFISICAL_BACKUP_CLIENT_SECRET='"'"'single quote, "double quote", and spaces'"'"''
} > "$source_file"

AC_TEST_MODE=1 \
AC_PRODUCTION_ENV_SOURCE="$source_file" \
AC_INFISICAL_BOOTSTRAP_TARGET="$target_file" \
  bash "$script" >/dev/null

[[ ! -e "$sentinel" ]]
[[ "$(stat -c '%a' "$target_file")" == 600 ]]
bash -c '
  set -euo pipefail
  source "$1"
  [[ "$INFISICAL_PROJECT_ID" == b421c44e-4599-4394-8df6-758ed8aedfed ]]
  [[ "$INFISICAL_VPS_CLIENT_ID" == "client id with spaces" ]]
  [[ "$INFISICAL_VPS_CLIENT_SECRET" == "\$(touch $2)" ]]
  [[ "$INFISICAL_BACKUP_CLIENT_ID" == "back\`tick; dollar \$HOME and #hash" ]]
  [[ "$INFISICAL_BACKUP_CLIENT_SECRET" == "single quote, \"double quote\", and spaces" ]]
' _ "$target_file" "$sentinel"
[[ ! -e "$sentinel" ]]

printf '%s\n' 'INFISICAL_VPS_CLIENT_ID=duplicate' >> "$source_file"
duplicate_target="$tmp_dir/secrets/duplicate.env"
if AC_TEST_MODE=1 \
  AC_PRODUCTION_ENV_SOURCE="$source_file" \
  AC_INFISICAL_BOOTSTRAP_TARGET="$duplicate_target" \
  bash "$script" >/dev/null 2>&1; then
  printf 'Duplicate bootstrap key was accepted.\n' >&2
  exit 1
fi
[[ ! -e "$duplicate_target" ]]

printf 'PASS  Infisical bootstrap serializes metacharacters without evaluation and rejects duplicates.\n'
