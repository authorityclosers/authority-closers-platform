#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { printf 'Run as root.\n' >&2; exit 1; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
policy_dir="$repo_root/config/release"
policy="$policy_dir/os-baseline.env"
packages_policy="$policy_dir/os-packages.tsv"
resolved_packages_policy="$policy_dir/os-resolved-packages.tsv"
[[ -r "$policy" && -r "$packages_policy" && -r "$resolved_packages_policy" ]] || {
  printf 'OS baseline policy is incomplete.\n' >&2
  exit 1
}

AC_OS_BASELINE_ID=''
AC_OS_ID=''
AC_OS_VERSION_ID=''
AC_OS_CODENAME=''
AC_OS_ARCH=''
AC_OS_RESOLVED_PACKAGES_SHA256=''
DOCKER_APT_KEY_SHA256=''
CLOUDFLARE_APT_KEY_SHA256=''
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  case "$key" in
    AC_OS_BASELINE_ID|AC_OS_ID|AC_OS_VERSION_ID|AC_OS_CODENAME|AC_OS_ARCH|AC_OS_RESOLVED_PACKAGES_SHA256|DOCKER_APT_KEY_SHA256|CLOUDFLARE_APT_KEY_SHA256)
      printf -v "$key" '%s' "$value"
      ;;
    *) printf 'Unknown OS baseline policy key: %s\n' "$key" >&2; exit 1 ;;
  esac
done < "$policy"

[[ "$AC_OS_BASELINE_ID" =~ ^[a-z0-9][a-z0-9.-]{7,127}$ ]]
[[ "$AC_OS_RESOLVED_PACKAGES_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$DOCKER_APT_KEY_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$CLOUDFLARE_APT_KEY_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$AC_OS_RESOLVED_PACKAGES_SHA256" == \
  "$(sha256sum "$resolved_packages_policy" | awk '{print $1}')" ]]
# shellcheck source=/dev/null
. /etc/os-release
[[ "$ID" == "$AC_OS_ID" && "$VERSION_ID" == "$AC_OS_VERSION_ID" && "$VERSION_CODENAME" == "$AC_OS_CODENAME" ]] || {
  printf 'Host OS does not match baseline %s.\n' "$AC_OS_BASELINE_ID" >&2
  exit 1
}
[[ "$(dpkg --print-architecture)" == "$AC_OS_ARCH" ]] || {
  printf 'Host architecture does not match baseline %s.\n' "$AC_OS_BASELINE_ID" >&2
  exit 1
}

declare -A expected_versions=()
packages=()
package_specs=()
while IFS=$'\t' read -r package version extra; do
  [[ -z "$package" || "$package" == \#* ]] && continue
  [[ -z "$extra" && "$package" =~ ^[a-z0-9][a-z0-9+.-]*$ && "$version" =~ ^[A-Za-z0-9.+:~_-]+$ ]] || {
    printf 'Invalid pinned package row: %s %s\n' "$package" "$version" >&2
    exit 1
  }
  [[ -z "${expected_versions[$package]:-}" ]] || { printf 'Duplicate pinned package: %s\n' "$package" >&2; exit 1; }
  expected_versions[$package]="$version"
  packages+=("$package")
  package_specs+=("$package=$version")
done < "$packages_policy"
((${#packages[@]} > 0)) || { printf 'Pinned package policy is empty.\n' >&2; exit 1; }

resolved_packages=()
while IFS=$'\t' read -r package version extra; do
  [[ -z "$package" || "$package" == \#* ]] && continue
  [[ -z "$extra" && "$package" =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9-]+)?$ \
    && -n "$version" ]] || {
    printf 'Invalid resolved package row: %s %s\n' "$package" "$version" >&2
    exit 1
  }
  resolved_packages+=("$package")
done < "$resolved_packages_policy"
((${#resolved_packages[@]} > 100)) || { printf 'Resolved package policy is incomplete.\n' >&2; exit 1; }

for conflicting in docker.io containerd runc; do
  if dpkg-query -W "$conflicting" >/dev/null 2>&1; then
    printf 'Conflicting distribution package is installed: %s\n' "$conflicting" >&2
    exit 1
  fi
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends --allow-downgrades \
  "ca-certificates=${expected_versions[ca-certificates]}" \
  "curl=${expected_versions[curl]}"

work_dir="$(mktemp -d /tmp/ac-os-baseline.XXXXXX)"
cleanup() {
  local status=$?
  case "$work_dir" in
    /tmp/ac-os-baseline.*) rm -rf -- "$work_dir" ;;
    *) printf 'Refusing to remove unexpected baseline path: %s\n' "$work_dir" >&2; status=1 ;;
  esac
  exit "$status"
}
trap cleanup EXIT

curl --fail --silent --show-error --location \
  https://download.docker.com/linux/ubuntu/gpg --output "$work_dir/docker.asc"
printf '%s  %s\n' "$DOCKER_APT_KEY_SHA256" "$work_dir/docker.asc" | sha256sum --check --strict
curl --fail --silent --show-error --location \
  https://pkg.cloudflare.com/cloudflare-main.gpg --output "$work_dir/cloudflare-main.gpg"
printf '%s  %s\n' "$CLOUDFLARE_APT_KEY_SHA256" "$work_dir/cloudflare-main.gpg" | sha256sum --check --strict

install -d -m 0755 /etc/apt/keyrings
install -o root -g root -m 0644 "$work_dir/docker.asc" /etc/apt/keyrings/docker.asc
install -o root -g root -m 0644 "$work_dir/cloudflare-main.gpg" /etc/apt/keyrings/cloudflare-main.gpg
printf '%s\n' \
  'Types: deb' \
  'URIs: https://download.docker.com/linux/ubuntu' \
  "Suites: $AC_OS_CODENAME" \
  'Components: stable' \
  "Architectures: $AC_OS_ARCH" \
  'Signed-By: /etc/apt/keyrings/docker.asc' \
  > /etc/apt/sources.list.d/docker.sources
printf 'deb [signed-by=/etc/apt/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared %s main\n' \
  "$AC_OS_CODENAME" > /etc/apt/sources.list.d/cloudflared.list

apt-get update
apt-get install -y --no-install-recommends --allow-downgrades "${package_specs[@]}"
for package in "${packages[@]}"; do
  installed="$(dpkg-query -W -f='${Version}' "$package")"
  [[ "$installed" == "${expected_versions[$package]}" ]] || {
    printf 'Pinned package mismatch: %s expected %s got %s\n' "$package" "${expected_versions[$package]}" "$installed" >&2
    exit 1
  }
done
record_root='/var/lib/authority-closers/baselines'
marker_root='/etc/authority-closers'
install -d -o root -g root -m 0750 "$record_root" "$marker_root"
manifest="$record_root/${AC_OS_BASELINE_ID}.packages.tsv"
dpkg-query -W -f='${binary:Package}\t${Version}\n' | LC_ALL=C sort > "$work_dir/packages.tsv"
if ! cmp --silent "$resolved_packages_policy" "$work_dir/packages.tsv"; then
  printf 'Resolved package graph differs from the committed baseline manifest.\n' >&2
  exit 1
fi
apt-mark hold "${resolved_packages[@]}" >/dev/null
install -o root -g root -m 0640 "$resolved_packages_policy" "$manifest"
manifest_sha="$(sha256sum "$manifest" | awk '{print $1}')"
policy_sha="$(sha256sum "$policy" | awk '{print $1}')"
packages_policy_sha="$(sha256sum "$packages_policy" | awk '{print $1}')"
resolved_packages_policy_sha="$(sha256sum "$resolved_packages_policy" | awk '{print $1}')"
marker_tmp="$work_dir/os-baseline.env"
printf '%s\n' \
  "AC_OS_BASELINE_ID=$AC_OS_BASELINE_ID" \
  "AC_OS_BASELINE_MANIFEST_SHA256=$manifest_sha" \
  "AC_OS_BASELINE_POLICY_SHA256=$policy_sha" \
  "AC_OS_PACKAGES_POLICY_SHA256=$packages_policy_sha" \
  "AC_OS_RESOLVED_PACKAGES_POLICY_SHA256=$resolved_packages_policy_sha" \
  > "$marker_tmp"
install -o root -g root -m 0644 "$marker_tmp" "$marker_root/os-baseline.env"

AC_BASELINE_POLICY_DIR="$policy_dir" "$repo_root/scripts/ac-os-baseline-verify"
printf 'PASS  Installed and recorded separately versioned OS baseline %s.\n' "$AC_OS_BASELINE_ID"
