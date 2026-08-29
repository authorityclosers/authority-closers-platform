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

bash "$foundation/scripts/validate-images-pinned.sh" >/dev/null
printf 'PASS  Immutable release installer covers all operational scripts/units and survives a clean-root smoke test.\n'
