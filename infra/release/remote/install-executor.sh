#!/usr/bin/env bash
# Source-only installer: an operator runs this on the new production host later.
# Installs no key, target config, service or timer and makes no runtime changes.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root on the approved executor host.' >&2; exit 1; }
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repository=$(cd "$source_dir/../.." && pwd)
# Do not run privileged Git against a writable workbench or user-owned checkout.
/usr/bin/python3 -I - "$repository" "$source_dir" <<'PY_TRUST'
import stat
import sys
from pathlib import Path
repository, source = map(Path, sys.argv[1:])
paths = [repository, repository / ".git", repository / ".git/config",
         source, source / "remote", *source.parents,
         *(source / name for name in ("ac_release.py", "ac_remote.py", "release_notes.py")),
         source / "remote/ac-release-executor"]
for path in paths:
    info = path.lstat()
    if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
        raise SystemExit("Executor installation requires root-owned, non-writable source paths.")
PY_TRUST
commit=$(git -C "$repository" rev-parse HEAD)
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || exit 1
[[ -z $(git -C "$repository" status --porcelain -- infra/release) ]] || {
  echo 'Install only the reviewed clean release sources.' >&2; exit 1;
}
release_dir="/opt/ac-release-executor/releases/$commit"
install -d -o root -g root -m 0755 /opt/ac-release-executor /opt/ac-release-executor/releases "$release_dir" "$release_dir/remote" /usr/local/libexec
for file in ac_release.py ac_remote.py release_notes.py; do
  install -o root -g root -m 0644 "$source_dir/$file" "$release_dir/$file"
done
install -o root -g root -m 0755 "$source_dir/remote/ac-release-executor" "$release_dir/remote/ac-release-executor"
ln -sfn "$release_dir" /opt/ac-release-executor/current.next
mv -T /opt/ac-release-executor/current.next /opt/ac-release-executor/current
cat > /usr/local/libexec/ac-release-executor.next <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 -I /opt/ac-release-executor/current/remote/ac-release-executor
WRAPPER
chown root:root /usr/local/libexec/ac-release-executor.next
chmod 0755 /usr/local/libexec/ac-release-executor.next
mv /usr/local/libexec/ac-release-executor.next /usr/local/libexec/ac-release-executor
install -d -o root -g root -m 0700 /etc/ac-release /var/lib/ac-release /var/lib/ac-release-executor /var/lib/ac-release-executor/incoming /srv/authority-closers/release-store
printf 'Installed inactive executor %s. No key, service, target or runtime was enabled.\n' "$commit"
