# Host disk alert

AUT-2165 adds a five-minute check of `/`, separate from nightly disk hygiene.
It uses `statvfs` with the same used/(used+available) rounding as `df`. It sends
one warning at 85%, one escalation at 95%, and a recovery below 80%. State is
updated only after the existing `ac-notify` transport succeeds; failed sends retry
on the next timer tick. Tokens are consumed only by that existing host transport.
The checker does not delete files, call providers, change services or touch databases.

`python3 infra/host-disk/ac_disk_alert.py` is a read-only dry run. Root installs
the committed, locally tested source with `bash infra/host-disk/install.sh --apply`
through the audited `ac-root` runner. The installer refuses to replace differing
existing files and compares every installed byte with the reviewed source.

Rollback: `systemctl disable --now ac-disk-alert.timer`. This disables only the
new timer and retains its state and journal. Existing nightly cleanup, production
holds and all application services are unchanged. No app release is involved.
