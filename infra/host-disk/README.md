# Host disk alert

AUT-2165 adds a five-minute check of `/`, separate from nightly disk hygiene.
It uses `statvfs` with the same used/(used+available) rounding as `df`. It sends
one warning at 85%, one escalation at 95%, and a recovery below 80%. State is
updated only after the existing `ac-notify` transport succeeds; failed sends retry
on the next timer tick. Tokens are consumed only by that existing host transport.
The checker does not delete files, call providers, change services or touch databases.

Root can run `python3 infra/host-disk/ac_disk_alert.py` for a read-only dry run. Root installs
the committed, locally tested source with `bash infra/host-disk/install.sh --apply`
through the audited `ac-root` runner. The installer refuses to replace differing
existing files and compares every installed byte with the reviewed source.

Rollback: `systemctl disable --now ac-disk-alert.timer`. This disables only the
new timer and retains its state and journal. Existing nightly cleanup, production
holds and all application services are unchanged. No app release is involved.

`clear_idle_next_cache.py` defaults to a dry run and only considers `.next/cache`
under retired lane checkouts. It preserves any app referenced by a process cwd or
file descriptor, refuses symlink redirects and retains compiled output.

`scripts/data-changes/aut2165_delete_host_files.py` rehearses the exact candidate
manifest attached to AUT-2165. It rejects altered manifests, paths, timestamps,
sizes, inodes, symlinks and hardlinks. The operator chooses explicit groups.
Apply additionally needs a private root-owned receipt binding the independently
verified owner's approve-delete record, selected groups, source-owner checks and
required production/board snapshot verification. The operator must reserve the
existing release/backup maintenance window and verify approval is still current.
The receipt itself grants no authority. Apply refuses open files and retains an
append-only host audit with per-file intents, results, approver and run identity.
No database is changed. No real data deletion has been authorized or applied.
