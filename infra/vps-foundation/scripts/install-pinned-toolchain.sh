#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_id="${AC_RELEASE_ID:-}"
policy="${AC_TOOLCHAIN_POLICY:-$repo_root/config/release/toolchain.env}"
[[ "$(id -u)" -eq 0 ]] || { printf 'Run as root.\n' >&2; exit 1; }
[[ "$release_id" =~ ^foundation-[0-9a-f]{40}$ ]] || {
  printf 'Set AC_RELEASE_ID to the full Git-SHA foundation release.\n' >&2
  exit 2
}
expected_policy="/srv/authority-closers/releases/$release_id/config/release/toolchain.env"
[[ "$(realpath -m -- "$policy")" == "$expected_policy" ]] || {
  printf 'Toolchain policy must come from the immutable target release.\n' >&2
  exit 1
}
[[ -r "$policy" ]] || { printf 'Toolchain policy is not readable: %s\n' "$policy" >&2; exit 1; }
[[ "$(dpkg --print-architecture)" == amd64 ]] || {
  printf 'The pinned operational toolchain currently supports amd64 only.\n' >&2
  exit 1
}

INFISICAL_VERSION=''
INFISICAL_LINUX_AMD64_SHA256=''
INFISICAL_LINUX_AMD64_BINARY_SHA256=''
RCLONE_VERSION=''
RCLONE_LINUX_AMD64_SHA256=''
RCLONE_LINUX_AMD64_BINARY_SHA256=''
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  case "$key" in
    INFISICAL_VERSION|INFISICAL_LINUX_AMD64_SHA256|INFISICAL_LINUX_AMD64_BINARY_SHA256|RCLONE_VERSION|RCLONE_LINUX_AMD64_SHA256|RCLONE_LINUX_AMD64_BINARY_SHA256)
      printf -v "$key" '%s' "$value"
      ;;
    *) printf 'Unknown toolchain policy key: %s\n' "$key" >&2; exit 1 ;;
  esac
done < "$policy"

[[ "$INFISICAL_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$RCLONE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$INFISICAL_LINUX_AMD64_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$INFISICAL_LINUX_AMD64_BINARY_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RCLONE_LINUX_AMD64_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RCLONE_LINUX_AMD64_BINARY_SHA256" =~ ^[0-9a-f]{64}$ ]]

download_release_asset() {
  local url=$1
  local destination=$2

  curl --ipv4 --fail --silent --show-error --location \
    --connect-timeout 10 --max-time 180 \
    --retry 3 --retry-all-errors --retry-delay 2 \
    "$url" --output "$destination"
}

work_dir="$(mktemp -d /tmp/ac-toolchain.XXXXXX)"
infisical_stage=''
rclone_stage=''
cleanup() {
  local status=$?
  for staged_binary in "$infisical_stage" "$rclone_stage"; do
    [[ -z "$staged_binary" || ! -e "$staged_binary" ]] && continue
    case "$staged_binary" in
      /usr/local/bin/.ac-infisical.*|/usr/local/bin/.ac-rclone.*) rm -f -- "$staged_binary" ;;
      *) printf 'Refusing to remove unexpected staged binary: %s\n' "$staged_binary" >&2; status=1 ;;
    esac
  done
  case "$work_dir" in
    /tmp/ac-toolchain.*) rm -rf -- "$work_dir" ;;
    *) printf 'Refusing to remove unexpected toolchain path: %s\n' "$work_dir" >&2; status=1 ;;
  esac
  exit "$status"
}
trap cleanup EXIT

infisical_archive="$work_dir/infisical.tar.gz"
download_release_asset \
  "https://github.com/Infisical/cli/releases/download/v${INFISICAL_VERSION}/cli_${INFISICAL_VERSION}_linux_amd64.tar.gz" \
  "$infisical_archive"
printf '%s  %s\n' "$INFISICAL_LINUX_AMD64_SHA256" "$infisical_archive" | sha256sum --check --strict
tar --extract --gzip --file "$infisical_archive" --directory "$work_dir" infisical

rclone_archive="$work_dir/rclone.zip"
download_release_asset \
  "https://github.com/rclone/rclone/releases/download/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-amd64.zip" \
  "$rclone_archive"
printf '%s  %s\n' "$RCLONE_LINUX_AMD64_SHA256" "$rclone_archive" | sha256sum --check --strict
unzip -q "$rclone_archive" "rclone-v${RCLONE_VERSION}-linux-amd64/rclone" -d "$work_dir"

printf '%s  %s\n' "$INFISICAL_LINUX_AMD64_BINARY_SHA256" "$work_dir/infisical" | sha256sum --check --strict
printf '%s  %s\n' \
  "$RCLONE_LINUX_AMD64_BINARY_SHA256" \
  "$work_dir/rclone-v${RCLONE_VERSION}-linux-amd64/rclone" \
  | sha256sum --check --strict
"$work_dir/infisical" --version | grep -q "$INFISICAL_VERSION"
"$work_dir/rclone-v${RCLONE_VERSION}-linux-amd64/rclone" version | grep -q "rclone v${RCLONE_VERSION}"
install -d -o root -g root -m 0755 /usr/local/bin
infisical_stage="$(mktemp /usr/local/bin/.ac-infisical.XXXXXX)"
rclone_stage="$(mktemp /usr/local/bin/.ac-rclone.XXXXXX)"
install -o root -g root -m 0755 "$work_dir/infisical" "$infisical_stage"
install -o root -g root -m 0755 \
  "$work_dir/rclone-v${RCLONE_VERSION}-linux-amd64/rclone" "$rclone_stage"
mv --force "$infisical_stage" /usr/local/bin/infisical
infisical_stage=''
mv --force "$rclone_stage" /usr/local/bin/rclone
rclone_stage=''

/usr/local/bin/infisical --version | grep -q "$INFISICAL_VERSION"
/usr/local/bin/rclone version | grep -q "rclone v${RCLONE_VERSION}"
marker_root='/var/lib/authority-closers/toolchains'
install -d -o root -g root -m 0750 "$marker_root"
marker="$work_dir/toolchain.env"
printf '%s\n' \
  "AC_RELEASE_ID=$release_id" \
  "TOOLCHAIN_POLICY_SHA256=$(sha256sum "$policy" | awk '{print $1}')" \
  "INFISICAL_VERSION=$INFISICAL_VERSION" \
  "INFISICAL_BINARY_SHA256=$INFISICAL_LINUX_AMD64_BINARY_SHA256" \
  "RCLONE_VERSION=$RCLONE_VERSION" \
  "RCLONE_BINARY_SHA256=$RCLONE_LINUX_AMD64_BINARY_SHA256" \
  > "$marker"
install -o root -g root -m 0640 "$marker" "$marker_root/${release_id}.env"
printf 'PASS  Installed checksum-pinned Infisical %s and rclone %s.\n' \
  "$INFISICAL_VERSION" "$RCLONE_VERSION"
