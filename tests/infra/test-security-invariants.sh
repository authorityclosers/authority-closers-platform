#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
foundation="$repo_root/infra/vps-foundation"

if grep -REn -- '--token=|--client-secret=' \
  "$foundation/scripts/ac-infisical-run" \
  "$foundation/scripts/ac-infisical-run-backup"; then
  printf 'Infisical credential or token is exposed through argv.\n' >&2
  exit 1
fi
grep -q 'export INFISICAL_TOKEN=' "$foundation/scripts/ac-infisical-run"
grep -q 'export INFISICAL_TOKEN=' "$foundation/scripts/ac-infisical-run-backup"

# The PowerShell token is intentionally literal in this static policy check.
# shellcheck disable=SC2016
if grep -Eq '\[Parameter\(Mandatory = \$true\)\].*(ApiToken|ApiKey)' \
  "$foundation/scripts/configure-cloudflare.ps1" \
  "$foundation/scripts/configure-resend-domain.ps1"; then
  printf 'Provider credential remains a PowerShell command-line parameter.\n' >&2
  exit 1
fi

grep -q 'DOCKER-USER chain is unavailable' "$foundation/scripts/ac-docker-firewall"
grep -q 'OnUnitActiveSec=60s' "$foundation/config/systemd/ac-docker-firewall.timer"
grep -q 'PartOf=docker.service' "$foundation/config/systemd/ac-docker-firewall.service"
grep -q 'ac-docker-firewall.timer' "$foundation/scripts/validate-foundation.sh"
grep -q 'ip6tables' "$foundation/scripts/validate-foundation.sh"
grep -q 'IPV6=yes' "$foundation/scripts/validate-foundation.sh"
grep -q 'ufw status numbered' "$foundation/scripts/bootstrap-host.sh"
grep -q 'parse-ufw-ssh-rules.sh' "$foundation/scripts/bootstrap-host.sh"

if grep -n 'tar .*|| true' "$foundation/scripts/bootstrap-host.sh"; then
  printf 'Rollback archive creation still suppresses tar failures.\n' >&2
  exit 1
fi

if find "$foundation/.github" -type f 2>/dev/null | grep -q .; then
  printf 'Nested GitHub workflows are inert and prohibited; checks belong at repository root.\n' >&2
  exit 1
fi

grep -Eq '^CADDY_IMAGE=.*@sha256:[0-9a-f]{64}$' "$foundation/config/release/foundation-images.env"
grep -Eq '^OTEL_IMAGE=.*@sha256:[0-9a-f]{64}$' "$foundation/config/release/foundation-images.env"
grep -Eq '^INFISICAL_LINUX_AMD64_SHA256=[0-9a-f]{64}$' "$foundation/config/release/toolchain.env"
grep -Eq '^INFISICAL_LINUX_AMD64_BINARY_SHA256=[0-9a-f]{64}$' "$foundation/config/release/toolchain.env"
grep -Eq '^RCLONE_LINUX_AMD64_SHA256=[0-9a-f]{64}$' "$foundation/config/release/toolchain.env"
grep -Eq '^RCLONE_LINUX_AMD64_BINARY_SHA256=[0-9a-f]{64}$' "$foundation/config/release/toolchain.env"
grep -q 'expected_infisical_binary_sha' "$foundation/scripts/ac-restic-restore-check-inner"
grep -q 'expected_rclone_binary_sha' "$foundation/scripts/ac-restic-restore-check-inner"
# shellcheck disable=SC2016  # This static assertion intentionally matches a literal variable reference.
grep -q 'trusted_release_dir="/srv/authority-closers/releases/$release_id"' \
  "$foundation/scripts/ac-restic-restore-check-inner"
# shellcheck disable=SC2016  # Restored binaries must remain inert data during the credentialed drill.
if grep -Eq '^"\$restored_(infisical|rclone)"' \
  "$foundation/scripts/ac-restic-restore-check-inner"; then
  printf 'Restore validation executes a binary sourced from the snapshot.\n' >&2
  exit 1
fi
grep -Fxq 'NoExecPaths=/tmp' "$foundation/config/systemd/ac-restic-restore-check.service"
# shellcheck disable=SC2016  # This static assertion intentionally matches a literal variable reference.
grep -q 'AC_TOOLCHAIN_POLICY="$release_dir/config/release/toolchain.env"' \
  "$foundation/scripts/install-foundation-release.sh"
grep -q 'git .*archive --format=tar' "$foundation/scripts/install-foundation-release.sh"
grep -q 'verify-git-release-archive.py' "$foundation/scripts/install-foundation-release.sh"
# shellcheck disable=SC2016  # This static assertion intentionally matches a literal variable reference.
grep -q 'AC_RELEASE_ARCHIVE="${AC_RELEASE_ARCHIVE:-}"' "$foundation/scripts/bootstrap-host.sh"
grep -q 'AC_RELEASE_ARCHIVE: "{{ ac_release_archive_remote }}"' \
  "$foundation/ansible/playbooks/bootstrap.yml"
controller_verify_line="$(grep -n 'Validate the exact archive on the trusted controller' \
  "$foundation/ansible/playbooks/bootstrap.yml" | cut -d: -f1)"
remote_extract_line="$(grep -n 'Extract only the checksum-verified Git archive' \
  "$foundation/ansible/playbooks/bootstrap.yml" | cut -d: -f1)"
[[ "$controller_verify_line" -lt "$remote_extract_line" ]]
grep -q 'Running installer differs from the checksum-verified release archive' \
  "$foundation/scripts/install-foundation-release.sh"
grep -q 'up --detach --remove-orphans --wait --wait-timeout 120' \
  "$foundation/scripts/install-foundation-release.sh"
grep -q 'restore_failed_transaction' "$foundation/scripts/install-foundation-release.sh"
# shellcheck disable=SC2016  # This static assertion intentionally matches a literal variable reference.
grep -q 'reconcile_compose_release "$previous_release_dir"' \
  "$foundation/scripts/install-foundation-release.sh"
grep -q 'full 40-character lowercase Git SHA' "$foundation/scripts/install-foundation-release.sh"

if grep -Eq 'dist-upgrade|apt-get install -y docker-ce|apt-get install -y cloudflared' \
  "$foundation/scripts/bootstrap-host.sh"; then
  printf 'Bootstrap contains mutable package installation outside the OS baseline gate.\n' >&2
  exit 1
fi

printf 'PASS  Foundation security invariants are represented in executable controls.\n'
