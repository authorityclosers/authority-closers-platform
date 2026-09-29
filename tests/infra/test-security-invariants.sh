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

grep -q 'AC_RESEND_TEST_RECIPIENT is required' \
  "$foundation/scripts/ac-resend-send-test-inner"
grep -q 'admin@authorityclosers.com' \
  "$foundation/scripts/ac-resend-send-test-inner"
# shellcheck disable=SC2016  # The static assertion intentionally matches a literal PowerShell variable.
grep -q '\[string\]\$ZoneName = "authorityclosers.com"' \
  "$foundation/scripts/configure-resend-domain.ps1"
# shellcheck disable=SC2016  # The static assertion intentionally matches a literal PowerShell variable.
grep -q '\[string\]\$DomainName = "authorityclosers.com"' \
  "$foundation/scripts/configure-resend-domain.ps1"

# The PowerShell token is intentionally literal in this static policy check.
# shellcheck disable=SC2016
if grep -Eq '\[Parameter\(Mandatory = \$true\)\].*(ApiToken|ApiKey)' \
  "$foundation/scripts/configure-cloudflare.ps1" \
  "$foundation/scripts/configure-resend-domain.ps1"; then
  printf 'Provider credential remains a PowerShell command-line parameter.\n' >&2
  exit 1
fi

grep -q 'DOCKER-USER chain is unavailable' "$foundation/scripts/ac-docker-firewall"
grep -q 'ac-docker-firewall-validate' "$foundation/scripts/ac-docker-firewall"
# shellcheck disable=SC2016  # This static assertion intentionally matches a literal variable reference.
if grep -q '"$binary" -A DOCKER-USER' "$foundation/scripts/ac-docker-firewall"; then
  printf 'Docker ingress DROP is appended after Docker-managed rules.\n' >&2
  exit 1
fi
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
grep -q 'apt-mark showhold' "$foundation/scripts/bootstrap-host.sh"

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
grep -q -- '--ipv4' "$foundation/scripts/install-pinned-toolchain.sh"
grep -q -- '--connect-timeout 10 --max-time 180' "$foundation/scripts/install-pinned-toolchain.sh"
grep -q -- '--retry 3 --retry-all-errors --retry-delay 2' "$foundation/scripts/install-pinned-toolchain.sh"
grep -q 'expected_infisical_binary_sha' "$foundation/scripts/ac-restic-restore-check-inner"
grep -q 'expected_rclone_binary_sha' "$foundation/scripts/ac-restic-restore-check-inner"
grep -Fq -- "--exclude='/srv/authority-closers/application/artifacts/**'" \
  "$foundation/scripts/ac-restic-backup-inner"
grep -Fq -- "--exclude='/srv/authority-closers/application/releases/**'" \
  "$foundation/scripts/ac-restic-backup-inner"
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
grep -Fxq '/usr/local/sbin/ac-infisical-run-backup' \
  "$foundation/config/release/install-scope-backup.txt"
[[ "$(grep -Ec '^/' "$foundation/config/release/install-scope-backup.txt")" -eq 26 ]]
grep -Fq 'AC_INSTALL_SCOPE accepts only backup.' "$foundation/scripts/install-foundation-release.sh"
# shellcheck disable=SC2016  # This exact source snippet is a static assertion.
grep -Fq 'if [[ "$test_mode" == 0 && "$scoped_backup_install" == 0 ]]; then' \
  "$foundation/scripts/install-foundation-release.sh"
# shellcheck disable=SC2016  # This exact source snippet is a static assertion.
[[ "$(grep -Fc 'if [[ "$scoped_backup_install" == 0 ]]; then' \
  "$foundation/scripts/install-foundation-release.sh")" -eq 3 ]]
# shellcheck disable=SC2016  # This exact source snippet is a static assertion.
grep -Fq 'elif [[ "$test_mode" == 0 ]]; then' \
  "$foundation/scripts/install-foundation-release.sh"
[[ "$(grep -Ec '^[[:space:]]+systemctl daemon-reload$' "$foundation/scripts/install-foundation-release.sh")" -eq 2 ]]
scope_check_line="$(grep -n 'AC_INSTALL_SCOPE accepts only backup' "$foundation/scripts/install-foundation-release.sh" | cut -d: -f1)"
# shellcheck disable=SC2016  # This exact source snippet is a static assertion.
root_create_line="$(grep -nF 'install -d -m 0750 "$srv_root"' "$foundation/scripts/install-foundation-release.sh" | cut -d: -f1)"
[[ "$scope_check_line" -lt "$root_create_line" ]]
# shellcheck disable=SC2016  # This exact activation branch is a static assertion.
backup_activation_block="$(sed -n \
  '/^activate_current_release() {$/,$p' "$foundation/scripts/install-foundation-release.sh" \
  | sed -n '/^if \[\[ "$scoped_backup_install" == 1 \]\]; then$/,/^elif \[\[ "$test_mode" == 0 \]\]; then$/p' \
  | sed '$d')"
for forbidden in ac-os-baseline-verify install-pinned-toolchain.sh reconcile_compose_release \
  ac-docker-firewall 'systemctl enable --now' 'curl --fail'; do
  if grep -Fq "$forbidden" <<<"$backup_activation_block"; then
    printf 'Scoped activation contains a full-install step: %s\n' "$forbidden" >&2
    exit 1
  fi
done
# shellcheck disable=SC2016  # This exact source snippet is a static assertion.
[[ "$(grep -nF 'if [[ "$test_mode" == 0 && "$scoped_backup_install" == 0 ]]; then' \
  "$foundation/scripts/install-foundation-release.sh" | head -n 1 | cut -d: -f1)" -lt \
  "$(grep -nF 'AC_BASELINE_POLICY_DIR=' "$foundation/scripts/install-foundation-release.sh" | cut -d: -f1)" ]]
# shellcheck disable=SC2016  # This exact source snippet is a static assertion.
grep -Fq 'resolve_installed_policy "$installed_root" "$scope_record"' \
  "$foundation/scripts/r2-usage-guard.sh"
grep -Fq 'foundation_policy_path(host_root)' "$foundation/scripts/ac-postgres-backup.py"
if grep -Eq '(^|[[:space:]])(export[[:space:]]+)?R2_POLICY_FILE=' \
  "$foundation/scripts/ac-r2-usage-guard"; then
  printf 'R2 wrapper overrides the installed scoped policy resolver.\n' >&2
  exit 1
fi

if grep -Eq 'dist-upgrade|apt-get install -y docker-ce|apt-get install -y cloudflared' \
  "$foundation/scripts/bootstrap-host.sh"; then
  printf 'Bootstrap contains mutable package installation outside the OS baseline gate.\n' >&2
  exit 1
fi

printf 'PASS  Foundation security invariants are represented in executable controls.\n'
