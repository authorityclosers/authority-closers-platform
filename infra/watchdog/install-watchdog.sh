#!/usr/bin/env bash
# Source-only installer. Root runs --install under the separate SHA-specific card.
set -euo pipefail

refuse() {
  echo 'Refused: unverified watchdog source' >&2
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
source_path='infra/watchdog/ac_watchdog.py'
installer_path='infra/watchdog/install-watchdog.sh'
target='/opt/ac-watchdog/ac_watchdog.py'

# No fetch, scratch files, sudo, config read or host writes during verification.
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
# Refuse an installer invoked from outside the verified tree (including a symlink).
[[ ! -L "${BASH_SOURCE[0]}" ]] || refuse
[[ "$script_dir/$(basename -- "${BASH_SOURCE[0]}")" == "$repo/$installer_path" ]] || refuse

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
[[ -d /opt/ac-watchdog && ! -L /opt/ac-watchdog ]] || {
  echo 'Install requires the existing /opt/ac-watchdog directory' >&2
  exit 1
}
if [[ -f "$target" && ! -L "$target" ]]; then
  installed="$(sha256sum -- "$target")"
  if [[ "${installed%% *}" == "$source_digest" ]]; then
    echo 'Already installed; no host files changed'
    exit 0
  fi
fi
stage="$(mktemp /opt/ac-watchdog/.ac-watchdog.XXXXXXXX)"
trap 'rm -f -- "$stage"' EXIT
git -C "$repo" show "$revision:$source_path" > "$stage"
staged="$(sha256sum -- "$stage")"
[[ "${staged%% *}" == "$source_digest" ]] || refuse
chown root:root "$stage"
chmod 0755 "$stage"
mv -fT -- "$stage" "$target"
installed="$(sha256sum -- "$target")"
[[ "${installed%% *}" == "$source_digest" ]] || refuse
echo "Installed source SHA256: $source_digest"
