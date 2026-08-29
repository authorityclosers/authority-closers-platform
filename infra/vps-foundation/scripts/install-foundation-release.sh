#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest="$repo_root/config/release/install-manifest.tsv"
release_id="${AC_RELEASE_ID:-}"
test_mode="${AC_TEST_MODE:-0}"
install_root="${AC_INSTALL_ROOT:-}"

[[ "$test_mode" == 0 || "$test_mode" == 1 ]] || {
  printf 'AC_TEST_MODE must be 0 or 1.\n' >&2
  exit 2
}

if [[ "$test_mode" == 1 ]]; then
  [[ -n "$install_root" && "$install_root" == /* ]] || {
    printf 'Test mode requires an explicit absolute AC_INSTALL_ROOT.\n' >&2
    exit 2
  }
  install_root="$(realpath -m -- "$install_root")"
  [[ "$install_root" != / ]] || {
    printf 'Refusing / as the test installation root.\n' >&2
    exit 2
  }
  [[ "$release_id" =~ ^foundation-test-[a-z0-9-]+$ ]] || {
    printf 'Test release IDs must match foundation-test-[a-z0-9-]+.\n' >&2
    exit 2
  }
else
  [[ -z "$install_root" ]] || {
    printf 'AC_INSTALL_ROOT is accepted only with AC_TEST_MODE=1.\n' >&2
    exit 2
  }
  [[ "$(id -u)" -eq 0 ]] || { printf 'Run as root.\n' >&2; exit 1; }
  [[ "$release_id" =~ ^foundation-[0-9a-f]{7,40}$ ]] || {
    printf 'Production release IDs must be foundation- plus a 7-40 character lowercase Git SHA.\n' >&2
    exit 2
  }
  getent group acops >/dev/null || {
    printf 'Required operator group does not exist: acops\n' >&2
    exit 1
  }
fi

[[ -r "$manifest" ]] || { printf 'Install manifest is not readable: %s\n' "$manifest" >&2; exit 1; }
if find "$repo_root" -type l -print -quit | grep -q .; then
  printf 'Release source contains a symbolic link; refusing ambiguous packaging.\n' >&2
  exit 1
fi

srv_root="${install_root}/srv/authority-closers"
releases_root="$srv_root/releases"
release_dir="$releases_root/$release_id"
current_link="$srv_root/current"
stage_dir=''

cleanup() {
  local status=$?
  if [[ -n "$stage_dir" && -e "$stage_dir" ]]; then
    case "$stage_dir" in
      "$releases_root"/.stage-*) rm -rf -- "$stage_dir" ;;
      *) printf 'Refusing to remove unexpected staging path: %s\n' "$stage_dir" >&2; status=1 ;;
    esac
  fi
  exit "$status"
}
trap cleanup EXIT

if [[ "$test_mode" == 1 ]]; then
  install -d -m 0750 "$srv_root" "$releases_root"
else
  install -d -m 2750 -o root -g acops "$srv_root" "$releases_root"
fi

if [[ -e "$release_dir" ]]; then
  [[ -f "$release_dir/RELEASE-ID" && "$(<"$release_dir/RELEASE-ID")" == "$release_id" ]] || {
    printf 'Existing immutable release has invalid identity metadata: %s\n' "$release_dir" >&2
    exit 1
  }
  (cd "$release_dir" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
else
  stage_dir="$(mktemp -d "$releases_root/.stage-${release_id}.XXXXXX")"
  cp -a "$repo_root/." "$stage_dir/"
  printf '%s\n' "$release_id" > "$stage_dir/RELEASE-ID"
  (
    cd "$stage_dir"
    mapfile -d '' -t release_files < <(find . -type f -print0 | LC_ALL=C sort -z)
    : > RELEASE-FILES.sha256
    for release_file in "${release_files[@]}"; do
      sha256sum "$release_file" >> RELEASE-FILES.sha256
    done
    sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null
  )
  find "$stage_dir" -type d -exec chmod 0750 {} +
  find "$stage_dir" -type f -exec chmod 0640 {} +
  find "$stage_dir/scripts" -type f -exec chmod 0750 {} +
  if [[ "$test_mode" == 0 ]]; then
    chown -R root:acops "$stage_dir"
  fi
  mv -- "$stage_dir" "$release_dir"
  stage_dir=''
fi

declare -A installed_targets=()
while IFS=$'\t' read -r kind source target mode owner group; do
  [[ -z "$kind" || "$kind" == \#* ]] && continue
  [[ "$kind" == executable || "$kind" == unit ]] || {
    printf 'Unsupported install kind: %s\n' "$kind" >&2
    exit 1
  }
  [[ "$source" != /* && "$source" != *'..'* ]] || {
    printf 'Unsafe release source path: %s\n' "$source" >&2
    exit 1
  }
  case "$target" in
    /usr/local/sbin/ac-*|/usr/local/libexec/authority-closers/*|/etc/systemd/system/ac-*|/etc/systemd/system/cloudflared.service) ;;
    *) printf 'Install target is outside the approved paths: %s\n' "$target" >&2; exit 1 ;;
  esac
  [[ "$mode" =~ ^0[467][0-7]{2}$ ]] || { printf 'Invalid install mode for %s.\n' "$target" >&2; exit 1; }
  [[ "$owner" == root && "$group" == root ]] || {
    printf 'Install ownership must be root:root for %s.\n' "$target" >&2
    exit 1
  }
  [[ -z "${installed_targets[$target]:-}" ]] || {
    printf 'Duplicate install target: %s\n' "$target" >&2
    exit 1
  }
  installed_targets[$target]=1

  source_path="$release_dir/$source"
  destination="${install_root}${target}"
  [[ -f "$source_path" ]] || { printf 'Manifest source is missing: %s\n' "$source" >&2; exit 1; }
  install -d -m 0755 "$(dirname "$destination")"
  if [[ "$test_mode" == 1 ]]; then
    install -m "$mode" "$source_path" "$destination"
  else
    install -o "$owner" -g "$group" -m "$mode" "$source_path" "$destination"
  fi
  cmp --silent "$source_path" "$destination" || {
    printf 'Installed file differs from release source: %s\n' "$target" >&2
    exit 1
  }
  [[ "$(stat -c '%a' "$destination")" == "${mode#0}" ]] || {
    printf 'Installed mode differs from manifest for %s.\n' "$target" >&2
    exit 1
  }
done < "$release_dir/config/release/install-manifest.tsv"

if [[ -e "$current_link" && ! -L "$current_link" ]]; then
  printf 'Current release path exists but is not a symbolic link: %s\n' "$current_link" >&2
  exit 1
fi
current_tmp="$srv_root/.current-${release_id}.$$"
ln -s "$release_dir" "$current_tmp"
mv --no-target-directory --force "$current_tmp" "$current_link"
[[ "$(readlink -f "$current_link")" == "$release_dir" ]] || {
  printf 'Current release link verification failed.\n' >&2
  exit 1
}

if [[ "$test_mode" == 0 ]]; then
  systemctl daemon-reload
fi

printf 'PASS  Installed immutable foundation release %s with %s managed host files.\n' \
  "$release_id" "${#installed_targets[@]}"
