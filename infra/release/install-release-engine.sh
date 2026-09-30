#!/usr/bin/env bash
# Install or update the AC release engine from this exact, clean checkout.
#
#   sudo infra/release/install-release-engine.sh
#
# A first install leaves staging auto-deploy PAUSED so the first deploy is
# supervised: run `ac-release deploy staging --dry-run`, then
# `ac-release deploy staging`, then `ac-release resume staging`.
set -euo pipefail

if [ "$(id -u)" != 0 ]; then
  printf 'Run as root (sudo).\n' >&2
  exit 1
fi
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$source_dir/../.." && pwd)"
commit="$(git -C "$repository" rev-parse HEAD)"
if ! [[ "$commit" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'Could not resolve the source commit.\n' >&2
  exit 1
fi
if [ -n "$(git -C "$repository" status --porcelain -- infra/release)" ]; then
  printf 'infra/release has uncommitted changes; install only reviewed commits.\n' >&2
  exit 1
fi

release_dir="/opt/ac-release/releases/$commit"
install -d -m 0755 /opt/ac-release /opt/ac-release/releases "$release_dir"
install -m 0644 "$source_dir/ac_release.py" "$release_dir/ac_release.py"
install -m 0644 "$source_dir/release_notes.py" "$release_dir/release_notes.py"
install -m 0644 "$source_dir/ac_train_notify.py" "$release_dir/ac_train_notify.py"
install -m 0644 "$source_dir/ac_train_watch.py" "$release_dir/ac_train_watch.py"
ln -sfn "$release_dir" /opt/ac-release/current.next
mv -T /opt/ac-release/current.next /opt/ac-release/current

cat > /usr/local/sbin/ac-release.next <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 /opt/ac-release/current/ac_release.py "$@"
WRAPPER
chmod 0755 /usr/local/sbin/ac-release.next
mv -f /usr/local/sbin/ac-release.next /usr/local/sbin/ac-release

cat > /usr/local/sbin/ac-train-notify.next <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 /opt/ac-release/current/ac_train_notify.py "$@"
WRAPPER
chmod 0755 /usr/local/sbin/ac-train-notify.next
mv -f /usr/local/sbin/ac-train-notify.next /usr/local/sbin/ac-train-notify

cat > /usr/local/sbin/ac-train-watch.next <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 /opt/ac-release/current/ac_train_watch.py "$@"
WRAPPER
chmod 0755 /usr/local/sbin/ac-train-watch.next
mv -f /usr/local/sbin/ac-train-watch.next /usr/local/sbin/ac-train-watch

install -d -m 0700 /etc/ac-release /var/lib/ac-release /srv/authority-closers/release-store
install -d -m 0700 /var/lib/ac-release/notify
install -d -m 0750 /var/log/ac-release

first_install=0
[ -f /etc/systemd/system/ac-release-tick.timer ] || first_install=1
install -m 0644 "$source_dir/systemd/ac-release-tick.service" /etc/systemd/system/ac-release-tick.service
install -m 0644 "$source_dir/systemd/ac-release-tick.timer" /etc/systemd/system/ac-release-tick.timer
install -m 0644 "$source_dir/systemd/ac-train-watch.service" /etc/systemd/system/ac-train-watch.service
install -m 0644 "$source_dir/systemd/ac-train-watch.timer" /etc/systemd/system/ac-train-watch.timer
if [ "$first_install" = 1 ] && [ ! -e /var/lib/ac-release/staging.paused ]; then
  printf '{"reason":"first install: run a supervised deploy, then ac-release resume staging"}\n' \
    > /var/lib/ac-release/staging.paused
fi
systemctl daemon-reload
systemctl enable --now ac-release-tick.timer
systemctl enable --now ac-train-watch.timer

if [ ! -s /etc/ac-release/github-actions-read.token ]; then
  printf 'WARNING: /etc/ac-release/github-actions-read.token is missing; deploys cannot download builds.\n' >&2
fi
printf 'Installed ac-release %s\n' "$commit"
/usr/local/sbin/ac-release status || true
