#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
foundation="$repo_root/infra/vps-foundation"
manifest="$foundation/config/release/install-manifest.tsv"

[[ -r "$manifest" ]]

while IFS= read -r source; do
  relative="${source#"$foundation/"}"
  grep -Fq $'\t'"$relative"$'\t' "$manifest" || {
    printf 'Operational script is absent from install manifest: %s\n' "$relative" >&2
    exit 1
  }
done < <(find "$foundation/scripts" -maxdepth 1 -type f -name 'ac-*' | LC_ALL=C sort)

for source in \
  scripts/r2-probe.sh \
  scripts/r2-usage-guard.sh \
  scripts/r2-usage-evaluate.sh \
  scripts/validate-foundation.sh; do
  grep -Fq $'\t'"$source"$'\t' "$manifest" || {
    printf 'Required operational script is absent from install manifest: %s\n' "$source" >&2
    exit 1
  }
done

while IFS= read -r source; do
  relative="${source#"$foundation/"}"
  grep -Fq $'\t'"$relative"$'\t' "$manifest" || {
    printf 'Systemd unit is absent from install manifest: %s\n' "$relative" >&2
    exit 1
  }
done < <(find "$foundation/config/systemd" -maxdepth 1 -type f | LC_ALL=C sort)

duplicate_targets="$(awk -F '\t' '!/^#/ && NF {count[$3]++} END {for (target in count) if (count[target] > 1) print target}' "$manifest")"
[[ -z "$duplicate_targets" ]] || {
  printf 'Duplicate install targets:\n%s\n' "$duplicate_targets" >&2
  exit 1
}

tmp_dir="$(mktemp -d -t ac-release-install-test.XXXXXX)"
cleanup() {
  local status=$?
  case "$tmp_dir" in
    /tmp/ac-release-install-test.*) rm -rf -- "$tmp_dir" ;;
    *) printf 'Refusing to remove unexpected release test path: %s\n' "$tmp_dir" >&2; status=1 ;;
  esac
  exit "$status"
}
trap cleanup EXIT

source_repo="$tmp_dir/source-repo"
source_foundation="$source_repo/infra/vps-foundation"
mkdir -p "$source_repo/infra"
cp -a "$foundation" "$source_foundation"
git -C "$source_repo" init -q
git -C "$source_repo" config user.name 'Authority Closers CI'
git -C "$source_repo" config user.email 'ci@authorityclosers.com'
git -C "$source_repo" add infra/vps-foundation
git -C "$source_repo" commit -qm 'fixture: exact foundation release'
release_sha="$(git -C "$source_repo" rev-parse HEAD)"
installer="$source_foundation/scripts/install-foundation-release.sh"
archive="$tmp_dir/foundation-${release_sha}.tar"
git -C "$source_repo" archive --format=tar --output="$archive" \
  "$release_sha" -- infra/vps-foundation
archive_sha="$(sha256sum "$archive" | awk '{print $1}')"
python3 "$source_foundation/scripts/verify-git-release-archive.py" \
  "$archive" "$archive_sha" "$release_sha" >/dev/null
wrong_release_sha="$(printf '0%.0s' {1..40})"
if python3 "$source_foundation/scripts/verify-git-release-archive.py" \
  "$archive" "$archive_sha" "$wrong_release_sha" >/dev/null 2>&1; then
  printf 'Archive verifier accepted an incorrect embedded Git commit.\n' >&2
  exit 1
fi
tampered_verifier="$source_foundation/scripts/verify-git-release-archive-tampered.py"
cp "$source_foundation/scripts/verify-git-release-archive.py" "$tampered_verifier"
printf '# controller mutation\n' >> "$tampered_verifier"
if python3 "$tampered_verifier" "$archive" "$archive_sha" "$release_sha" >/dev/null 2>&1; then
  printf 'Archive verifier accepted a controller verifier outside the exact commit.\n' >&2
  exit 1
fi

unsafe_archive="$tmp_dir/unsafe-release.tar"
python3 - "$unsafe_archive" "$release_sha" <<'PY'
from __future__ import annotations

import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "w", format=tarfile.PAX_FORMAT,
                  pax_headers={"comment": sys.argv[2]}) as archive:
    payload = b"escape\n"
    entry = tarfile.TarInfo("../escape")
    entry.size = len(payload)
    archive.addfile(entry, io.BytesIO(payload))
PY
unsafe_archive_sha="$(sha256sum "$unsafe_archive" | awk '{print $1}')"
if python3 "$source_foundation/scripts/verify-git-release-archive.py" \
  "$unsafe_archive" "$unsafe_archive_sha" "$release_sha" >/dev/null 2>&1; then
  printf 'Archive verifier accepted a path traversal entry.\n' >&2
  exit 1
fi
printf 'UNTRACKED-WORKTREE-MUTATION\n' >> "$source_foundation/compose/foundation/Caddyfile"

AC_TEST_MODE=1 \
AC_INSTALL_ROOT="$tmp_dir/root" \
AC_RELEASE_ID=foundation-test-ci \
AC_RELEASE_GIT_SHA="$release_sha" \
  bash "$installer" >/dev/null

release="$tmp_dir/root/srv/authority-closers/releases/foundation-test-ci"
current="$tmp_dir/root/srv/authority-closers/current"
[[ -L "$current" ]]
[[ "$(readlink -f "$current")" == "$release" ]]
(cd "$release" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
[[ "$(<"$release/RELEASE-COMMIT")" == "$release_sha" ]]
if grep -q 'UNTRACKED-WORKTREE-MUTATION' "$release/compose/foundation/Caddyfile"; then
  printf 'Release included content outside the exact Git commit.\n' >&2
  exit 1
fi

while IFS=$'\t' read -r kind source target mode owner group; do
  [[ -z "$kind" || "$kind" == \#* ]] && continue
  destination="$tmp_dir/root$target"
  [[ -f "$destination" ]]
  cmp --silent "$release/$source" "$destination"
  [[ "$(stat -c '%a' "$destination")" == "${mode#0}" ]]
  [[ "$owner:$group" == 'root:root' ]]
done < "$release/config/release/install-manifest.tsv"

AC_TEST_MODE=1 \
AC_INSTALL_ROOT="$tmp_dir/archive-root" \
AC_RELEASE_ID=foundation-test-archive \
AC_RELEASE_GIT_SHA="$release_sha" \
AC_RELEASE_ARCHIVE="$archive" \
AC_RELEASE_ARCHIVE_SHA256="$archive_sha" \
  bash "$installer" >/dev/null
archive_release="$tmp_dir/archive-root/srv/authority-closers/releases/foundation-test-archive"
[[ "$(<"$archive_release/RELEASE-COMMIT")" == "$release_sha" ]]
if grep -q 'UNTRACKED-WORKTREE-MUTATION' "$archive_release/compose/foundation/Caddyfile"; then
  printf 'Archive-mode release included a working-tree mutation.\n' >&2
  exit 1
fi

if AC_TEST_MODE=1 \
  AC_INSTALL_ROOT="$tmp_dir/bad-hash-root" \
  AC_RELEASE_ID=foundation-test-bad-hash \
  AC_RELEASE_GIT_SHA="$release_sha" \
  AC_RELEASE_ARCHIVE="$archive" \
  AC_RELEASE_ARCHIVE_SHA256="$(printf '0%.0s' {1..64})" \
  bash "$installer" >/dev/null 2>&1; then
  printf 'Archive mode accepted an incorrect SHA-256.\n' >&2
  exit 1
fi

tampered_installer="$source_foundation/scripts/install-foundation-release-tampered.sh"
cp "$installer" "$tampered_installer"
printf '# working-tree mutation\n' >> "$tampered_installer"
if AC_TEST_MODE=1 \
  AC_INSTALL_ROOT="$tmp_dir/tampered-installer-root" \
  AC_RELEASE_ID=foundation-test-tampered-installer \
  AC_RELEASE_GIT_SHA="$release_sha" \
  AC_RELEASE_ARCHIVE="$archive" \
  AC_RELEASE_ARCHIVE_SHA256="$archive_sha" \
  bash "$tampered_installer" >/dev/null 2>&1; then
  printf 'Archive mode accepted an installer outside the exact commit.\n' >&2
  exit 1
fi

installed_health="$tmp_dir/root/usr/local/sbin/ac-foundation-health"
installed_health_sha="$(sha256sum "$installed_health" | awk '{print $1}')"
printf '# candidate transaction fixture\n' >> "$source_foundation/scripts/ac-foundation-health"
git -C "$source_repo" add infra/vps-foundation/scripts/ac-foundation-health
git -C "$source_repo" commit -qm 'fixture: candidate release transaction'
candidate_sha="$(git -C "$source_repo" rev-parse HEAD)"
if AC_TEST_MODE=1 \
  AC_TEST_FAIL_AFTER_INSTALL=1 \
  AC_INSTALL_ROOT="$tmp_dir/root" \
  AC_RELEASE_ID=foundation-test-transaction \
  AC_RELEASE_GIT_SHA="$candidate_sha" \
  bash "$installer" >/dev/null 2>&1; then
  printf 'Injected post-install failure unexpectedly succeeded.\n' >&2
  exit 1
fi
[[ "$(readlink -f "$current")" == "$release" ]]
[[ "$(sha256sum "$installed_health" | awk '{print $1}')" == "$installed_health_sha" ]]
if AC_TEST_MODE=1 \
  AC_TEST_FAIL_AFTER_ACTIVATE=1 \
  AC_INSTALL_ROOT="$tmp_dir/root" \
  AC_RELEASE_ID=foundation-test-transaction \
  AC_RELEASE_GIT_SHA="$candidate_sha" \
  bash "$installer" >/dev/null 2>&1; then
  printf 'Injected post-activation failure unexpectedly succeeded.\n' >&2
  exit 1
fi
[[ "$(readlink -f "$current")" == "$release" ]]
[[ "$(sha256sum "$installed_health" | awk '{print $1}')" == "$installed_health_sha" ]]

bash "$foundation/scripts/validate-images-pinned.sh" >/dev/null
printf 'PASS  Immutable installer binds release evidence and rolls back a failed host transaction.\n'
