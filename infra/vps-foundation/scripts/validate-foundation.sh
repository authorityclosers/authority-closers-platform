#!/usr/bin/env bash
set -euo pipefail

failures=0
external_interface="${AC_EXTERNAL_INTERFACE:-eth0}"

check() {
  local description="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS  %s\n' "$description"
  else
    printf 'FAIL  %s\n' "$description"
    failures=$((failures + 1))
  fi
}

ufw_denies_public_ssh() {
  local status
  status="$(ufw status numbered)"
  grep -qx 'Status: active' <<<"$status"
  if grep -Ei '(22/tcp|OpenSSH)' <<<"$status" | grep -Eq '[[:space:]]ALLOW([[:space:]]|$)'; then
    return 1
  fi
  ufw status verbose | grep -q 'Default: deny (incoming), allow (outgoing), deny (routed)'
  grep -Eq '^IPV6=yes$' /etc/default/ufw
}

check 'named administrator exists' id suyash
check 'root SSH login disabled' bash -c "sshd -T | grep -qx 'permitrootlogin no'"
check 'SSH password authentication disabled' bash -c "sshd -T | grep -qx 'passwordauthentication no'"
check 'SSH restricted to operator group' bash -c "sshd -T | grep -qx 'allowgroups ssh-users'"
check 'UFW active' bash -c "ufw status | grep -qx 'Status: active'"
check 'UFW effectively denies public IPv4 and IPv6 TCP/22' ufw_denies_public_ssh
check 'auditd active' systemctl is-active --quiet auditd
check 'fail2ban active' systemctl is-active --quiet fail2ban
check 'fail2ban SSH jail active' bash -c "fail2ban-client status sshd | grep -q 'Status for the jail: sshd'"
check 'unattended upgrades active' systemctl is-active --quiet unattended-upgrades
check 'AppArmor enabled' bash -c "aa-status | grep -q 'apparmor module is loaded'"
check 'swap enabled' bash -c "swapon --show=NAME --noheadings | grep -q ."
check 'Docker active' systemctl is-active --quiet docker
check 'Docker default log driver is local' bash -c "docker info --format '{{.LoggingDriver}}' | grep -qx local"
check 'Docker socket is not TCP exposed' bash -c "! ss -ltn | grep -Eq ':(2375|2376)[[:space:]]'"
check 'Docker group has no users' bash -c "getent group docker | grep -Eq '^docker:x:[0-9]+:$'"
check 'Docker IPv4 public-ingress guard installed' \
  iptables -C DOCKER-USER -i "$external_interface" -j DROP
check 'Docker IPv6 public-ingress guard installed' \
  ip6tables -C DOCKER-USER -i "$external_interface" -j DROP
check 'AC edge network exists' docker network inspect ac_edge
check 'AC telemetry network exists' docker network inspect ac_telemetry
check 'no public HTTP listener on host' bash -c "! ss -ltn | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]):(80|443)[[:space:]]'"
check 'foundation local health responds' curl --fail --silent --max-time 5 http://127.0.0.1:8080/healthz
check 'edge container is healthy' bash -c "docker inspect ac-edge-router --format '{{.State.Health.Status}}' | grep -qx healthy"
check 'foundation containers use read-only roots' bash -c "test \"$(docker inspect ac-edge-router ac-telemetry-collector --format '{{.HostConfig.ReadonlyRootfs}}' | grep -c '^true$')\" -eq 2"
check 'foundation containers are not privileged' bash -c "test \"$(docker inspect ac-edge-router ac-telemetry-collector --format '{{.HostConfig.Privileged}}' | grep -c '^false$')\" -eq 2"
check 'foundation containers prevent privilege escalation' bash -c "docker inspect ac-edge-router ac-telemetry-collector --format '{{json .HostConfig.SecurityOpt}}' | grep -vc 'no-new-privileges:true' | grep -qx 0"

if [[ -f /etc/cloudflared/tunnel-token ]]; then
  check 'Cloudflare Tunnel connector active' systemctl is-active --quiet cloudflared
  check 'Cloudflare Tunnel token directory is restricted' bash -c "test \"$(stat -c '%U:%G %a' /etc/cloudflared)\" = 'root:cloudflared 750'"
  check 'Cloudflare Tunnel token is restricted' bash -c "test \"$(stat -c '%U:%G %a' /etc/cloudflared/tunnel-token)\" = 'root:cloudflared 640'"
fi

if [[ -n "${AC_PUBLIC_HEALTH_URL:-}" ]]; then
  check 'public tunnel health responds' curl --fail --silent --show-error --max-time 15 "$AC_PUBLIC_HEALTH_URL"
fi

if [[ "$failures" -ne 0 ]]; then
  printf '%s validation check(s) failed.\n' "$failures" >&2
  exit 1
fi
