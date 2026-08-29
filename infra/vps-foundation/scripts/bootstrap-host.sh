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
  local stamp archive
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="/root/ac-bootstrap-backups/pre-change-${stamp}.tar.gz"
  install -d -m 0700 /root/ac-bootstrap-backups
  tar --acls --xattrs -czf "$archive" \
    /etc/ssh /etc/ufw /etc/apt/apt.conf.d /etc/systemd/journald.conf \
    /etc/systemd/journald.conf.d /etc/sysctl.conf /etc/sysctl.d \
    /etc/fstab 2>/dev/null || true
  chmod 0600 "$archive"
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

phase_harden() {
  id "$admin_user" >/dev/null
  id -nG "$admin_user" | grep -qw ssh-users

  if ! systemctl is-active --quiet cloudflared && [[ "${AC_ALLOW_PUBLIC_SSH_BOOTSTRAP:-0}" != '1' ]]; then
    printf '%s\n' \
      'Refusing to reset the firewall without an active Cloudflare connector.' \
      'For a fresh host only, explicitly set AC_ALLOW_PUBLIC_SSH_BOOTSTRAP=1,' \
      'then run the lockdown phase after the Access SSH path is verified.' >&2
    exit 1
  fi

  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get -y dist-upgrade
  apt-get install -y --no-install-recommends \
    apparmor apparmor-utils auditd audispd-plugins ca-certificates curl fail2ban \
    gnupg jq logrotate needrestart rclone restic rsync sysstat ufw unattended-upgrades unzip

  # Infisical moved its CLI packages from Cloudsmith to its official repository.
  # Keep future rebuilds on the supported source before installing the CLI.
  if [[ ! -f /etc/apt/sources.list.d/infisical.list ]]; then
    curl -1sLf https://artifacts-cli.infisical.com/setup.deb.sh | bash
  fi
  apt-get update
  apt-get install -y --no-install-recommends infisical

  # The Ubuntu package can lag behind R2 S3 API behavior. Keep the single
  # static client on the current official stable release.
  curl --fail --silent --show-error https://rclone.org/install.sh | bash

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
  if [[ "${AC_CLOUDFLARE_SSH_VERIFIED:-}" != 'YES' ]]; then
    printf 'Set AC_CLOUDFLARE_SSH_VERIFIED=YES only after a second session proves the Access SSH path.\n' >&2
    exit 1
  fi

  systemctl is-active --quiet cloudflared
  ufw --force delete allow 22/tcp >/dev/null 2>&1 || true
  ufw reload

  if ufw status | grep -qE '(^|[[:space:]])22/tcp[[:space:]]+ALLOW'; then
    printf 'Public SSH allow rule still exists after lock-down.\n' >&2
    exit 1
  fi

  printf 'PASS  Public TCP/22 is denied; retain the independently verified Cloudflare Access session.\n'
}

phase_runtime() {
  export DEBIAN_FRONTEND=noninteractive
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  arch="$(dpkg --print-architecture)"
  # shellcheck source=/dev/null
  codename="$(. /etc/os-release && printf '%s' "$VERSION_CODENAME")"
  printf '%s\n' \
    'Types: deb' \
    'URIs: https://download.docker.com/linux/ubuntu' \
    "Suites: $codename" \
    'Components: stable' \
    "Architectures: $arch" \
    'Signed-By: /etc/apt/keyrings/docker.asc' \
    > /etc/apt/sources.list.d/docker.sources
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /etc/apt/keyrings/cloudflare-main.gpg
  chmod a+r /etc/apt/keyrings/cloudflare-main.gpg
  install -m 0644 "$repo_root/config/apt/cloudflared.list" /etc/apt/sources.list.d/cloudflared.list
  apt-get update
  apt-get install -y cloudflared

  install -d -m 0755 /etc/docker
  install -m 0644 "$repo_root/config/docker/daemon.json" /etc/docker/daemon.json
  dockerd --validate --config-file=/etc/docker/daemon.json

  install -d -m 2750 -o root -g acops \
    /srv/authority-closers/compose/foundation \
    /srv/authority-closers/releases \
    /srv/authority-closers/runbooks \
    /srv/authority-closers/backups \
    /srv/authority-closers/volumes/postgres \
    /srv/authority-closers/volumes/blob \
    /srv/authority-closers/volumes/media \
    /srv/authority-closers/volumes/mailpit \
    /srv/authority-closers/volumes/otel
  install -d -m 0750 -o root -g acops /srv/authority-closers/env

  install -m 0640 -o root -g acops "$repo_root/compose/foundation/compose.yaml" /srv/authority-closers/compose/foundation/compose.yaml
  # These are non-secret bind-mounted configs and must be readable by the
  # unprivileged UIDs inside their containers.
  install -m 0644 -o root -g acops "$repo_root/compose/foundation/Caddyfile" /srv/authority-closers/compose/foundation/Caddyfile
  install -m 0644 -o root -g acops "$repo_root/compose/foundation/otel-collector.yaml" /srv/authority-closers/compose/foundation/otel-collector.yaml
  install -m 0640 -o root -g acops "$repo_root/runbooks/OPERATIONS.md" /srv/authority-closers/runbooks/OPERATIONS.md

  install -m 0755 "$repo_root/scripts/ac-docker-firewall" /usr/local/sbin/ac-docker-firewall
  install -m 0755 "$repo_root/scripts/ac-foundation-health" /usr/local/sbin/ac-foundation-health
  install -m 0644 "$repo_root/config/systemd/ac-docker-firewall.service" /etc/systemd/system/ac-docker-firewall.service
  install -m 0644 "$repo_root/config/systemd/ac-foundation-health.service" /etc/systemd/system/ac-foundation-health.service
  install -m 0644 "$repo_root/config/systemd/ac-foundation-health.timer" /etc/systemd/system/ac-foundation-health.timer
  install -m 0644 "$repo_root/config/systemd/cloudflared.service" /etc/systemd/system/cloudflared.service
  getent passwd cloudflared >/dev/null || useradd --system --user-group --home-dir /var/lib/cloudflared --shell /usr/sbin/nologin cloudflared
  install -d -m 0750 -o root -g cloudflared /etc/cloudflared

  systemctl daemon-reload
  systemctl restart docker
  docker network inspect ac_edge >/dev/null 2>&1 || docker network create ac_edge
  docker network inspect ac_telemetry >/dev/null 2>&1 || docker network create ac_telemetry --internal
  systemctl enable --now ac-docker-firewall.service ac-foundation-health.timer
}

require_root
case "$phase" in
  access) phase_access ;;
  harden) phase_harden ;;
  lockdown) phase_lockdown ;;
  runtime) phase_runtime ;;
  *) printf 'Usage: %s {access PUBLIC_KEY_PATH|harden|lockdown|runtime}\n' "$0" >&2; exit 2 ;;
esac
