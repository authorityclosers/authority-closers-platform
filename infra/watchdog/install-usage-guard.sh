#!/usr/bin/env bash
# Source-only installer. Root runs --install under the separate SHA-specific card.
set -euo pipefail

refuse() {
  echo 'Refused: unverified usage-guard source' >&2
  exit 2
}

revision=''
mode=''
while (($#)); do
  case "$1" in
    --source-revision)
      (($# >= 2)) && [[ -z "$revision" ]] || refuse
      revision="$2"
      shift 2
      ;;
    --dry-run|--install)
      [[ -z "$mode" ]] || refuse
      mode="$1"
      shift
      ;;
    *) refuse ;;
  esac
done
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || refuse
mode="${mode:---dry-run}"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || refuse
repo="$(git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null)" || refuse
source_path='infra/watchdog/ac_usage_guard.py'
installer_path='infra/watchdog/install-usage-guard.sh'
target='/opt/ac-watchdog/ac_usage_guard.py'

# No fetch, scratch files, credential reads or host writes during verification.
commit="$(git -C "$repo" rev-parse --verify "$revision^{commit}" 2>/dev/null)" || refuse
[[ "$commit" == "$revision" ]] || refuse
git -C "$repo" merge-base --is-ancestor "$revision" refs/remotes/origin/main 2>/dev/null || refuse
for path in "$source_path" "$installer_path"; do
  [[ -f "$repo/$path" && ! -L "$repo/$path" ]] || refuse
  tree="$(git -C "$repo" ls-tree "$revision" -- "$path" 2>/dev/null)" || refuse
  [[ "$tree" == "100755 blob "* ]] || refuse
  expected="$(git -C "$repo" show "$revision:$path" 2>/dev/null | sha256sum)" || refuse
  actual="$(sha256sum -- "$repo/$path")" || refuse
  [[ "${expected%% *}" == "${actual%% *}" ]] || refuse
  if [[ "$path" == "$source_path" ]]; then
    source_digest="${expected%% *}"
  fi
done
[[ ! -L "${BASH_SOURCE[0]}" ]] || refuse
[[ "$script_dir/$(basename -- "${BASH_SOURCE[0]}")" == "$repo/$installer_path" ]] || refuse

# Parse only; never import the guard or invoke its refresh/runtime dependencies.
python3 - "$repo/$source_path" 2>/dev/null <<'PY' || refuse
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text())
bound = any(
    isinstance(node, ast.Import)
    and any(alias.name == "subprocess" and alias.asname in (None, "subprocess")
            for alias in node.names)
    for node in tree.body
)
refresh = any(
    isinstance(node, ast.FunctionDef) and node.name == "keep_token_fresh"
    for node in tree.body
)
if not bound or not refresh:
    sys.exit(1)
PY

echo "Verified source revision: $revision"
echo "Verified source SHA256: $source_digest"
if [[ "$mode" == '--dry-run' ]]; then
  echo "Dry-run: would install $source_path to $target; no host files changed"
  exit 0
fi

if ((EUID != 0)); then
  echo 'Install requires Root under the separate SHA-specific install card' >&2
  exit 1
fi
[[ -d /opt/ac-watchdog && ! -L /opt/ac-watchdog ]] || refuse
# The existing guard is required so every replacement retains a rollback artifact.
[[ -f "$target" && ! -L "$target" ]] || refuse
installed="$(sha256sum -- "$target")"
prior_digest="${installed%% *}"
echo "Prior source SHA256: $prior_digest"
if [[ "$prior_digest" == "$source_digest" ]]; then
  echo 'Already installed; no host files changed'
  exit 0
fi

stage=''
backup_stage=''
cleanup() {
  [[ -z "$stage" ]] || rm -f -- "$stage"
  [[ -z "$backup_stage" ]] || rm -f -- "$backup_stage"
  return 0
}
trap cleanup EXIT
stage="$(mktemp /opt/ac-watchdog/.ac-usage-guard.XXXXXXXX)"
git -C "$repo" show "$revision:$source_path" > "$stage"
staged="$(sha256sum -- "$stage")"
[[ "${staged%% *}" == "$source_digest" ]] || refuse
chown root:root "$stage"
chmod 0755 "$stage"

backup="$target.rollback.$prior_digest"
if [[ -e "$backup" || -L "$backup" ]]; then
  [[ -f "$backup" && ! -L "$backup" ]] || refuse
else
  backup_stage="$(mktemp /opt/ac-watchdog/.ac-usage-guard-backup.XXXXXXXX)"
  cp -p -- "$target" "$backup_stage"
  saved="$(sha256sum -- "$backup_stage")"
  [[ "${saved%% *}" == "$prior_digest" ]] || refuse
  # Publish without overwriting an existing artifact, even on a concurrent run.
  ln -- "$backup_stage" "$backup"
fi
saved="$(sha256sum -- "$backup")"
[[ "${saved%% *}" == "$prior_digest" ]] || refuse
echo "Rollback artifact: $backup"

# Refuse drift after backup; replace only the source, without service/hold changes.
[[ -f "$target" && ! -L "$target" ]] || refuse
installed="$(sha256sum -- "$target")"
[[ "${installed%% *}" == "$prior_digest" ]] || refuse
mv -fT -- "$stage" "$target"
installed="$(sha256sum -- "$target")"
[[ "${installed%% *}" == "$source_digest" ]] || refuse
echo "Installed source SHA256: $source_digest"
