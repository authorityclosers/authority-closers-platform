#!/usr/bin/env bash
set -euo pipefail

phase="${1:-}"
admin_key_path="${2:-}"
admin_user="${AC_ADMIN_USER:-suyash}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    printf 'Run as root.\n' >&2
    exit 1
  fi
}

backup_host_config() {
  local stamp archive package_manifest candidate
  local -a candidates paths
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="/root/ac-bootstrap-backups/pre-change-${stamp}.tar.gz"
  package_manifest="/root/ac-bootstrap-backups/pre-change-${stamp}.packages.tsv"
  install -d -m 0700 /root/ac-bootstrap-backups

  shopt -s nullglob
  candidates=(
    /etc/ssh
    /etc/ufw
    /etc/apt/apt.conf.d
    /etc/apt/sources.list.d
    /etc/systemd/journald.conf
    /etc/systemd/journald.conf.d
    /etc/systemd/system/ac-*.service
    /etc/systemd/system/ac-*.timer
    /etc/systemd/system/cloudflared.service
    /etc/sysctl.conf
    /etc/sysctl.d
    /etc/fail2ban
    /etc/audit/rules.d
    /etc/security/limits.d
    /etc/docker
    /etc/fstab
    /etc/authority-closers/os-baseline.env
    /var/lib/authority-closers/baselines
    /var/lib/authority-closers/toolchains
    /usr/local/bin/infisical
    /usr/local/bin/rclone
    /usr/local/sbin/ac-*
    /usr/local/libexec/authority-closers
    /srv/authority-closers/current
  )
  shopt -u nullglob
  paths=()
  for candidate in "${candidates[@]}"; do
    if [[ -e "$candidate" || -L "$candidate" ]]; then
      paths+=("${candidate#/}")
    fi
  done
  ((${#paths[@]} > 0)) || {
    printf 'No rollback source paths exist; refusing to continue.\n' >&2
    exit 1
  }

  tar --acls --xattrs --numeric-owner --directory=/ --create --gzip --file="$archive" "${paths[@]}"
  tar --list --gzip --file="$archive" etc/ssh >/dev/null || {
    printf 'Rollback archive verification failed: %s\n' "$archive" >&2
    rm -f -- "$archive"
    exit 1
  }
  chmod 0600 "$archive"
  dpkg-query -W -f='${binary:Package}\t${Version}\n' | LC_ALL=C sort > "$package_manifest"
  [[ -s "$package_manifest" ]] || { printf 'Rollback package manifest is empty.\n' >&2; exit 1; }
  chmod 0600 "$package_manifest"
  printf 'Created rollback archive %s\n' "$archive"
}

phase_access() {
  if [[ -z "$admin_key_path" || ! -s "$admin_key_path" ]]; then
    printf 'Usage: %s access /path/to/admin-public-key\n' "$0" >&2
    exit 1
  fi

  backup_host_config
  getent group ssh-users >/dev/null || groupadd --system ssh-users
  getent group acops >/dev/null || groupadd --system acops

  if ! id "$admin_user" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$admin_user"
  fi
  usermod --append --groups sudo,ssh-users,acops "$admin_user"
  passwd --lock "$admin_user" >/dev/null

  install -d -m 0700 -o "$admin_user" -g "$admin_user" "/home/$admin_user/.ssh"
  install -m 0600 -o "$admin_user" -g "$admin_user" "$admin_key_path" "/home/$admin_user/.ssh/authorized_keys"

  printf '%s ALL=(ALL:ALL) NOPASSWD:ALL\n' "$admin_user" > "/etc/sudoers.d/90-${admin_user}"
  chmod 0440 "/etc/sudoers.d/90-${admin_user}"
  visudo --check --file "/etc/sudoers.d/90-${admin_user}"
}

phase_baseline() {
  backup_host_config
  "$repo_root/scripts/install-os-baseline.sh"
}

phase_harden() {
  id "$admin_user" >/dev/null
  id -nG "$admin_user" | grep -qw ssh-users
  AC_BASELINE_POLICY_DIR="$repo_root/config/release" "$repo_root/scripts/ac-os-baseline-verify"

  if [[ "${AC_ALLOW_PUBLIC_SSH_BOOTSTRAP:-0}" != '1' && "${AC_CLOUDFLARE_SSH_VERIFIED:-}" != 'YES' ]]; then
    printf '%s\n' \
      'Refusing to reset the firewall without an explicit access-path decision.' \
      'For a fresh host, set AC_ALLOW_PUBLIC_SSH_BOOTSTRAP=1 temporarily.' \
      'After a second session proves Access SSH, set AC_CLOUDFLARE_SSH_VERIFIED=YES.' >&2
    exit 1
  fi
  if [[ "${AC_CLOUDFLARE_SSH_VERIFIED:-}" == 'YES' ]]; then
    systemctl is-active --quiet cloudflared
  fi

  backup_host_config

  hostnamectl set-hostname ac-kvm4-prod
  if ! grep -qE '^127\.0\.1\.1[[:space:]]+ac-kvm4-prod([[:space:]]|$)' /etc/hosts; then
    printf '127.0.1.1 ac-kvm4-prod\n' >> /etc/hosts
  fi

  install -d -m 0755 /etc/ssh/sshd_config.d /etc/fail2ban/jail.d /etc/sysctl.d /etc/docker
  install -d -m 0755 /etc/systemd/journald.conf.d /etc/audit/rules.d /etc/security/limits.d
  rm -f /etc/ssh/sshd_config.d/90-authority-closers.conf
  install -m 0644 "$repo_root/config/ssh/00-authority-closers.conf" /etc/ssh/sshd_config.d/00-authority-closers.conf
  install -m 0644 "$repo_root/config/fail2ban/authority-closers.local" /etc/fail2ban/jail.d/authority-closers.local
  install -m 0644 "$repo_root/config/sysctl/90-authority-closers.conf" /etc/sysctl.d/90-authority-closers.conf
  install -m 0644 "$repo_root/config/journald/90-authority-closers.conf" /etc/systemd/journald.conf.d/90-authority-closers.conf
  install -m 0640 "$repo_root/config/audit/90-authority-closers.rules" /etc/audit/rules.d/90-authority-closers.rules
  install -m 0644 "$repo_root/config/apt/52authority-closers-unattended-upgrades" /etc/apt/apt.conf.d/52authority-closers-unattended-upgrades
  install -m 0644 "$repo_root/config/limits/90-authority-closers.conf" /etc/security/limits.d/90-authority-closers.conf

  if ! swapon --show=NAME --noheadings | grep -q .; then
    fallocate -l 4G /swapfile
    chmod 0600 /swapfile
    mkswap /swapfile
    swapon /swapfile
  fi
  if ! grep -qE '^/swapfile[[:space:]]' /etc/fstab; then
    printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
  fi

  install -d -m 2750 -o root -g acops /srv/authority-closers
  install -d -m 0755 /var/log/journal
  install -d -m 0750 /etc/cloudflared
  install -d -m 0700 /etc/authority-closers/secrets
  install -d -m 0750 /srv/authority-closers/compose /srv/authority-closers/env

  sysctl --system >/dev/null
  sshd -t
  augenrules --load

  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing
  ufw default deny routed
  ufw logging medium
  if [[ "${AC_ALLOW_PUBLIC_SSH_BOOTSTRAP:-0}" == '1' ]]; then
    ufw allow 22/tcp comment 'TEMPORARY Authority Closers SSH bootstrap'
  fi
  ufw --force enable

  systemctl enable --now auditd fail2ban sysstat unattended-upgrades
  systemctl restart systemd-journald fail2ban ssh
}

phase_lockdown() {
  local rule_number
  local -a public_ssh_rules
  if [[ "${AC_CLOUDFLARE_SSH_VERIFIED:-}" != 'YES' ]]; then
    printf 'Set AC_CLOUDFLARE_SSH_VERIFIED=YES only after a second session proves the Access SSH path.\n' >&2
    exit 1
  fi

  systemctl is-active --quiet cloudflared
  backup_host_config
  mapfile -t public_ssh_rules < <(
    ufw status numbered | "$repo_root/scripts/parse-ufw-ssh-rules.sh"
  )
  for rule_number in "${public_ssh_rules[@]}"; do
    ufw --force delete "$rule_number"
  done
  ufw reload

  if ufw status numbered | grep -Ei '(22/tcp|OpenSSH)' | grep -Eq '[[:space:]]ALLOW([[:space:]]|$)'; then
    printf 'Public SSH allow rule still exists after lock-down.\n' >&2
    exit 1
  fi

  printf 'PASS  Public TCP/22 is denied; retain the independently verified Cloudflare Access session.\n'
}

phase_runtime() {
  local release_id compose_file image_env_file
  release_id="${AC_RELEASE_ID:-}"
  [[ "$release_id" =~ ^foundation-[0-9a-f]{40}$ ]] || {
    printf 'Set AC_RELEASE_ID=foundation-<full-reviewed-git-sha> for the runtime phase.\n' >&2
    exit 2
  }

  AC_BASELINE_POLICY_DIR="$repo_root/config/release" "$repo_root/scripts/ac-os-baseline-verify"
  backup_host_config

  install -d -m 0755 /etc/docker
  install -m 0644 "$repo_root/config/docker/daemon.json" /etc/docker/daemon.json
  dockerd --validate --config-file=/etc/docker/daemon.json
  systemctl restart docker

  install -d -m 2750 -o root -g acops \
    /srv/authority-closers/releases \
    /srv/authority-closers/backups \
    /srv/authority-closers/volumes/postgres \
    /srv/authority-closers/volumes/blob \
    /srv/authority-closers/volumes/media \
    /srv/authority-closers/volumes/mailpit \
    /srv/authority-closers/volumes/otel
  install -d -m 0750 -o root -g acops /srv/authority-closers/env
  install -d -m 0750 /var/cache/authority-closers-restic
  install -d -m 0700 /etc/authority-closers/secrets
  getent passwd cloudflared >/dev/null || useradd --system --user-group --home-dir /var/lib/cloudflared --shell /usr/sbin/nologin cloudflared
  install -d -m 0750 -o root -g cloudflared /etc/cloudflared

  AC_RELEASE_ID="$release_id" "$repo_root/scripts/install-foundation-release.sh"

  docker network inspect ac_edge >/dev/null 2>&1 || docker network create ac_edge
  docker network inspect ac_telemetry >/dev/null 2>&1 || docker network create ac_telemetry --internal
  systemctl enable --now ac-docker-firewall.service ac-docker-firewall.timer

  compose_file='/srv/authority-closers/current/compose/foundation/compose.yaml'
  image_env_file='/srv/authority-closers/current/config/release/foundation-images.env'
  docker compose --env-file "$image_env_file" -f "$compose_file" config --quiet
  docker compose --env-file "$image_env_file" -f "$compose_file" up --detach --remove-orphans

  systemctl enable --now ac-foundation-health.timer
  if [[ -f /etc/cloudflared/tunnel-token ]]; then
    [[ "$(stat -c '%U:%G %a' /etc/cloudflared/tunnel-token)" == 'root:cloudflared 640' ]] || {
      printf 'Cloudflare Tunnel token ownership or mode is unsafe.\n' >&2
      exit 1
    }
    systemctl enable --now cloudflared.service
  else
    printf 'PENDING  Cloudflared is installed but not activated because the root-owned tunnel token is absent.\n'
  fi

  /usr/local/sbin/ac-foundation-health
}

phase_activate() {
  local target="${1:-}"
  [[ -L /srv/authority-closers/current ]] || {
    printf 'Install a reviewed immutable runtime release before activation.\n' >&2
    exit 1
  }
  backup_host_config

  case "$target" in
    cloudflared)
      [[ -f /etc/cloudflared/tunnel-token ]] || { printf 'Cloudflare Tunnel token is absent.\n' >&2; exit 1; }
      [[ "$(stat -c '%U:%G %a' /etc/cloudflared/tunnel-token)" == 'root:cloudflared 640' ]] || {
        printf 'Cloudflare Tunnel token ownership or mode is unsafe.\n' >&2
        exit 1
      }
      systemctl enable --now cloudflared.service
      systemctl is-active --quiet cloudflared.service
      ;;
    r2-jobs)
      [[ -r /etc/authority-closers/secrets/infisical-bootstrap.env ]] || {
        printf 'Infisical bootstrap is absent; refusing to activate R2 writers.\n' >&2
        exit 1
      }
      /usr/local/sbin/ac-infisical-verify
      /usr/local/sbin/ac-r2-usage-guard
      /usr/local/sbin/ac-restic-restore-check
      systemctl enable --now \
        ac-r2-usage-guard.timer \
        ac-restic-backup.timer \
        ac-restic-restore-check.timer
      ;;
    *)
      printf 'Usage: %s activate {cloudflared|r2-jobs}\n' "$0" >&2
      exit 2
      ;;
  esac
}

require_root
case "$phase" in
  access) phase_access ;;
  baseline) phase_baseline ;;
  harden) phase_harden ;;
  lockdown) phase_lockdown ;;
  runtime) phase_runtime ;;
  activate) phase_activate "$admin_key_path" ;;
  *) printf 'Usage: %s {access PUBLIC_KEY_PATH|baseline|harden|runtime|activate TARGET|lockdown}\n' "$0" >&2; exit 2 ;;
esac
