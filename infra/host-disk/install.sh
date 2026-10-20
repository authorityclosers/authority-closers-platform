#!/usr/bin/env bash
# Only installs this task's new disk alert. Default mode makes no host changes.
set -euo pipefail
mode="${1:---dry-run}"
[[ $# -le 1 && ( "$mode" == --dry-run || "$mode" == --apply ) ]] || exit 2
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
files=(ac_disk_alert.py ac-disk-alert.service ac-disk-alert.timer)
for name in "${files[@]}"; do
  [[ -f "$here/$name" && ! -L "$here/$name" ]] || exit 2
done
sha256sum "${files[@]/#/$here/}"
if [[ "$mode" == --dry-run ]]; then
  echo 'Would install ac-disk-alert and enable its five-minute timer; no existing service is changed.'
  exit 0
fi
[[ $EUID -eq 0 ]] || { echo 'Root required' >&2; exit 1; }
targets=(/usr/local/sbin/ac-disk-alert /etc/systemd/system/ac-disk-alert.service /etc/systemd/system/ac-disk-alert.timer)
# This installer must never replace unrelated or modified host files.
for i in "${!files[@]}"; do
  if [[ -e "${targets[$i]}" || -L "${targets[$i]}" ]]; then
    [[ -f "${targets[$i]}" && ! -L "${targets[$i]}" ]] || exit 2
    cmp -s "$here/${files[$i]}" "${targets[$i]}" || { echo 'Existing disk alert differs; refused' >&2; exit 2; }
  fi
done
install -m 0755 "$here/ac_disk_alert.py" /usr/local/sbin/ac-disk-alert
install -m 0644 "$here/ac-disk-alert.service" "$here/ac-disk-alert.timer" /etc/systemd/system/
for i in "${!files[@]}"; do cmp -s "$here/${files[$i]}" "${targets[$i]}"; done
systemctl daemon-reload
systemctl enable --now ac-disk-alert.timer
systemctl start ac-disk-alert.service
sha256sum "${targets[@]}"
