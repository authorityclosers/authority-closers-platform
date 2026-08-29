#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
policy="$repo_root/config/release/toolchain.env"
[[ -r "$policy" ]] || { printf 'Toolchain policy is not readable: %s\n' "$policy" >&2; exit 1; }
[[ "$(dpkg --print-architecture)" == amd64 ]] || {
  printf 'The pinned operational toolchain currently supports amd64 only.\n' >&2
  exit 1
}

INFISICAL_VERSION=''
INFISICAL_LINUX_AMD64_SHA256=''
RCLONE_VERSION=''
RCLONE_LINUX_AMD64_SHA256=''
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  case "$key" in
    INFISICAL_VERSION|INFISICAL_LINUX_AMD64_SHA256|RCLONE_VERSION|RCLONE_LINUX_AMD64_SHA256)
      printf -v "$key" '%s' "$value"
      ;;
    *) printf 'Unknown toolchain policy key: %s\n' "$key" >&2; exit 1 ;;
  esac
done < "$policy"

[[ "$INFISICAL_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$RCLONE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$INFISICAL_LINUX_AMD64_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RCLONE_LINUX_AMD64_SHA256" =~ ^[0-9a-f]{64}$ ]]

work_dir="$(mktemp -d /tmp/ac-toolchain.XXXXXX)"
cleanup() {
  local status=$?
  case "$work_dir" in
    /tmp/ac-toolchain.*) rm -rf -- "$work_dir" ;;
    *) printf 'Refusing to remove unexpected toolchain path: %s\n' "$work_dir" >&2; status=1 ;;
  esac
  exit "$status"
}
trap cleanup EXIT

infisical_archive="$work_dir/infisical.tar.gz"
curl --fail --silent --show-error --location \
  "https://github.com/Infisical/cli/releases/download/v${INFISICAL_VERSION}/cli_${INFISICAL_VERSION}_linux_amd64.tar.gz" \
  --output "$infisical_archive"
printf '%s  %s\n' "$INFISICAL_LINUX_AMD64_SHA256" "$infisical_archive" | sha256sum --check --strict
tar --extract --gzip --file "$infisical_archive" --directory "$work_dir" infisical
install -o root -g root -m 0755 "$work_dir/infisical" /usr/local/bin/infisical

rclone_archive="$work_dir/rclone.zip"
curl --fail --silent --show-error --location \
  "https://github.com/rclone/rclone/releases/download/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-amd64.zip" \
  --output "$rclone_archive"
printf '%s  %s\n' "$RCLONE_LINUX_AMD64_SHA256" "$rclone_archive" | sha256sum --check --strict
unzip -q "$rclone_archive" -d "$work_dir"
install -o root -g root -m 0755 \
  "$work_dir/rclone-v${RCLONE_VERSION}-linux-amd64/rclone" \
  /usr/local/bin/rclone

/usr/local/bin/infisical --version | grep -q "$INFISICAL_VERSION"
/usr/local/bin/rclone version | grep -q "rclone v${RCLONE_VERSION}"
printf 'PASS  Installed checksum-pinned Infisical %s and rclone %s.\n' \
  "$INFISICAL_VERSION" "$RCLONE_VERSION"
