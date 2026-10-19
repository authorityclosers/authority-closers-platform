#!/usr/bin/env bash
# Configure collection without installing collector/SQL/alerts/service/timer bytes.
# This deliberately holds post-export hooks: their release/activation is separate.
set -euo pipefail

apply=false
environments=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) apply=true; shift ;;
    --environments)
      [[ $# -ge 2 ]] || { printf 'Missing environments.\n' >&2; exit 2; }
      environments="$2"; shift 2 ;;
    *) printf 'Usage: configure-metrics-collection.sh [--apply] --environments "development staging [production]"\n' >&2; exit 2 ;;
  esac
done
[[ "$environments" == 'development staging' || "$environments" == 'development staging production' ]] || {
  printf 'Select development staging, optionally followed by production.\n' >&2
  exit 2
}

dropin=/etc/systemd/system/ac-metrics-collect.service.d/80-collection-policy.conf
policy="$(cat <<EOF
# AUT-2122: persistent collection selection, independent of installed unit bytes.
[Service]
Environment="AC_METRICS_ENVIRONMENTS=$environments"
# Hold unreleased post-export alerts. Keep their installed files unchanged.
# Remove this reset only in a separately reviewed alerts activation.
ExecStartPost=
EOF
)"
printf '%s\n%s\n' "$dropin" "$policy"
if [[ "$apply" == false ]]; then
  printf 'Dry run only. Add --apply to save and reload systemd; no unit is started.\n'
  exit 0
fi
[[ "$(id -u)" == 0 ]] || { printf 'Run as root to apply.\n' >&2; exit 1; }
[[ -f /etc/systemd/system/ac-metrics-collect.service &&
   -f /etc/systemd/system/ac-metrics-collect.timer &&
   -x /usr/local/sbin/ac-metrics-collect ]] || {
  printf 'An installed collector, service and timer are required.\n' >&2
  exit 1
}
[[ ! -L "${dropin%/*}" && ! -L "$dropin" ]] || {
  printf 'Collector policy must not use symbolic links.\n' >&2
  exit 1
}
install -d -m 0755 "${dropin%/*}"
temporary=$(mktemp "${dropin%/*}/.collection-policy.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
printf '%s\n' "$policy" > "$temporary"
chmod 0644 "$temporary"
chown root:root "$temporary"
mv -fT -- "$temporary" "$dropin"
systemctl daemon-reload
printf 'Saved collection policy. Timer and collector were not started or restarted.\n'
