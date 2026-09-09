#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_id="${AC_RELEASE_ID:-}"
release_sha="${AC_RELEASE_GIT_SHA:-}"
release_archive="${AC_RELEASE_ARCHIVE:-}"
release_archive_sha="${AC_RELEASE_ARCHIVE_SHA256:-}"
test_mode="${AC_TEST_MODE:-0}"
install_root="${AC_INSTALL_ROOT:-}"
test_fail_after_install="${AC_TEST_FAIL_AFTER_INSTALL:-0}"
test_fail_after_activate="${AC_TEST_FAIL_AFTER_ACTIVATE:-0}"
approved_legacy_release_id="${AC_APPROVED_LEGACY_RELEASE_ID:-}"

[[ "$test_mode" == 0 || "$test_mode" == 1 ]] || {
  printf 'AC_TEST_MODE must be 0 or 1.\n' >&2
  exit 2
}
[[ "$test_fail_after_install" == 0 || "$test_fail_after_install" == 1 ]] || {
  printf 'AC_TEST_FAIL_AFTER_INSTALL must be 0 or 1.\n' >&2
  exit 2
}
[[ "$test_fail_after_activate" == 0 || "$test_fail_after_activate" == 1 ]] || {
  printf 'AC_TEST_FAIL_AFTER_ACTIVATE must be 0 or 1.\n' >&2
  exit 2
}
[[ "$test_mode" == 1 || ( "$test_fail_after_install" == 0 && "$test_fail_after_activate" == 0 ) ]] || {
  printf 'Failure injection is accepted only in test mode.\n' >&2
  exit 2
}
if [[ -n "$approved_legacy_release_id" && ! "$approved_legacy_release_id" =~ ^infra-[0-9a-f]{7,40}$ ]]; then
  printf 'AC_APPROVED_LEGACY_RELEASE_ID must be an explicit historical infra release ID.\n' >&2
  exit 2
fi

if [[ "$test_mode" == 1 ]]; then
  [[ -n "$install_root" && "$install_root" == /* ]] || {
    printf 'Test mode requires an explicit absolute AC_INSTALL_ROOT.\n' >&2
    exit 2
  }
  install_root="$(realpath -m -- "$install_root")"
  [[ "$install_root" != / ]] || {
    printf 'Refusing / as the test installation root.\n' >&2
    exit 2
  }
  [[ "$release_id" =~ ^foundation-test-[a-z0-9-]+$ ]] || {
    printf 'Test release IDs must match foundation-test-[a-z0-9-]+.\n' >&2
    exit 2
  }
  [[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'Test mode requires AC_RELEASE_GIT_SHA as a full 40-character Git commit.\n' >&2
    exit 2
  }
else
  [[ -z "$install_root" ]] || {
    printf 'AC_INSTALL_ROOT is accepted only with AC_TEST_MODE=1.\n' >&2
    exit 2
  }
  [[ "$(id -u)" -eq 0 ]] || { printf 'Run as root.\n' >&2; exit 1; }
  [[ "$release_id" =~ ^foundation-[0-9a-f]{40}$ ]] || {
    printf 'Production release IDs must be foundation- plus a full 40-character lowercase Git SHA.\n' >&2
    exit 2
  }
  release_sha="${release_id#foundation-}"
  getent group acops >/dev/null || {
    printf 'Required operator group does not exist: acops\n' >&2
    exit 1
  }
fi
if [[ -n "$release_archive" || -n "$release_archive_sha" ]]; then
  [[ "$release_archive" == /* && -r "$release_archive" && "$release_archive_sha" =~ ^[0-9a-f]{64}$ ]] || {
    printf 'Archive mode requires an absolute readable archive and its SHA-256.\n' >&2
    exit 2
  }
fi

srv_root="${install_root}/srv/authority-closers"
releases_root="$srv_root/releases"
release_dir="$releases_root/$release_id"
current_link="$srv_root/current"
stage_dir=''
rollback_dir=''
transaction_active=0
transaction_committed=0
compose_mutated=0
application_edge_routes_root="$srv_root/application/edge-routes"
application_root="$srv_root/application"
application_edge_route_releases_root="$application_root/edge-route-releases"
foundation_edge_route_projection="$application_edge_route_releases_root/$release_id"
application_edge_routes_root_created=0
previous_link_target=''
previous_release_dir=''
previous_release_mode=''
legacy_compose_root="$srv_root/compose/foundation"
legacy_compose_file="$legacy_compose_root/compose.yaml"
legacy_env_file="$srv_root/env/foundation.env"
declare -a transaction_targets=()

reconcile_compose_release() {
  local target_release compose_file image_env_file
  local -a expected_services running_services
  target_release="$1"
  compose_file="$target_release/compose/foundation/compose.yaml"
  image_env_file="$target_release/config/release/foundation-images.env"
  docker compose --env-file "$image_env_file" -f "$compose_file" config --quiet
  mapfile -t expected_services < <(
    docker compose --env-file "$image_env_file" -f "$compose_file" config --services
  )
  ((${#expected_services[@]} > 0))
  docker compose --env-file "$image_env_file" -f "$compose_file" \
    up --detach --remove-orphans --wait --wait-timeout 120
  mapfile -t running_services < <(
    docker compose --env-file "$image_env_file" -f "$compose_file" \
      ps --status running --services
  )
  [[ "${#running_services[@]}" -eq "${#expected_services[@]}" ]]
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/healthz >/dev/null
}

validate_legacy_foundation() {
  local previous_id=$1
  local -a actual_files expected_files legacy_files

  [[ -n "$approved_legacy_release_id" && "$previous_id" == "$approved_legacy_release_id" ]] || {
    printf 'Legacy foundation rollback requires an exact AC_APPROVED_LEGACY_RELEASE_ID.\n' >&2
    exit 1
  }
  expected_files=(Caddyfile compose.yaml otel-collector.yaml)
  mapfile -t actual_files < <(
    find "$legacy_compose_root" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort
  )
  [[ "${actual_files[*]}" == "${expected_files[*]}" ]] || {
    printf 'Legacy foundation Compose directory has an unexpected file set.\n' >&2
    exit 1
  }
  if find "$legacy_compose_root" -mindepth 1 -maxdepth 1 ! -type f -print -quit | grep -q .; then
    printf 'Legacy foundation Compose directory contains a non-regular entry.\n' >&2
    exit 1
  fi
  [[ -f "$legacy_env_file" && ! -L "$legacy_env_file" ]] || {
    printf 'Legacy foundation image environment is not a regular file.\n' >&2
    exit 1
  }
  [[ "$(stat -c '%U:%G %a' "$legacy_compose_root")" == 'root:acops 2750' ]]
  [[ "$(stat -c '%U:%G %a' "$legacy_compose_file")" == 'root:acops 640' ]]
  [[ "$(stat -c '%U:%G %a' "$legacy_compose_root/Caddyfile")" == 'root:acops 644' ]]
  [[ "$(stat -c '%U:%G %a' "$legacy_compose_root/otel-collector.yaml")" == 'root:acops 644' ]]
  [[ "$(stat -c '%U:%G %a' "$legacy_env_file")" == 'root:acops 640' ]]
  if grep -Ev \
    '^(CADDY_IMAGE=caddy@sha256:[0-9a-f]{64}|OTEL_IMAGE=otel/opentelemetry-collector-contrib@sha256:[0-9a-f]{64})$' \
    "$legacy_env_file" | grep -q .; then
    printf 'Legacy foundation image environment is not exact and digest-pinned.\n' >&2
    exit 1
  fi
  [[ "$(wc -l < "$legacy_env_file")" -eq 2 ]]
  docker compose --env-file "$legacy_env_file" -f "$legacy_compose_file" config --quiet

  legacy_files=(
    "$legacy_compose_file"
    "$legacy_compose_root/Caddyfile"
    "$legacy_compose_root/otel-collector.yaml"
    "$legacy_env_file"
  )
  sha256sum "${legacy_files[@]}" > "$rollback_dir/legacy-foundation.sha256"
  sha256sum --check --strict "$rollback_dir/legacy-foundation.sha256" >/dev/null
}

reconcile_legacy_foundation() {
  local -a expected_services running_services

  sha256sum --check --strict "$rollback_dir/legacy-foundation.sha256" >/dev/null
  docker compose --env-file "$legacy_env_file" -f "$legacy_compose_file" config --quiet
  mapfile -t expected_services < <(
    docker compose --env-file "$legacy_env_file" -f "$legacy_compose_file" config --services
  )
  ((${#expected_services[@]} > 0))
  docker compose --env-file "$legacy_env_file" -f "$legacy_compose_file" \
    up --detach --remove-orphans --wait --wait-timeout 120
  mapfile -t running_services < <(
    docker compose --env-file "$legacy_env_file" -f "$legacy_compose_file" \
      ps --status running --services
  )
  [[ "${#running_services[@]}" -eq "${#expected_services[@]}" ]]
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/healthz >/dev/null
}

restore_current_link() {
  local rollback_link
  if [[ -n "$previous_link_target" ]]; then
    rollback_link="$srv_root/.rollback-current-${release_id}.$$"
    rm -f -- "$rollback_link"
    ln -s "$previous_link_target" "$rollback_link"
    mv --no-target-directory --force "$rollback_link" "$current_link"
  else
    rm -f -- "$current_link"
  fi
}

restore_failed_transaction() {
  local rollback_failed=0 target
  printf 'ROLLBACK  Restoring host state after failed release %s.\n' "$release_id" >&2

  for target in "${transaction_targets[@]}"; do
    rm -f -- "$target" || rollback_failed=1
  done
  if [[ -s "$rollback_dir/host-files.tar" ]]; then
    tar --acls --xattrs --numeric-owner --directory=/ \
      --extract --file="$rollback_dir/host-files.tar" || rollback_failed=1
  fi
  restore_current_link || rollback_failed=1
  if [[ "$application_edge_routes_root_created" == 1 ]]; then
    rmdir -- "$application_edge_routes_root" || rollback_failed=1
  fi

  if [[ "$test_mode" == 0 ]]; then
    systemctl daemon-reload || rollback_failed=1
    if [[ "$compose_mutated" == 1 ]]; then
      if [[ "$previous_release_mode" == immutable ]]; then
        reconcile_compose_release "$previous_release_dir" || rollback_failed=1
        /usr/local/sbin/ac-docker-firewall || rollback_failed=1
        systemctl enable --now \
          ac-docker-firewall.service \
          ac-docker-firewall.timer \
          ac-foundation-health.timer || rollback_failed=1
      elif [[ "$previous_release_mode" == legacy ]]; then
        reconcile_legacy_foundation || rollback_failed=1
        /usr/local/sbin/ac-docker-firewall || rollback_failed=1
        systemctl enable --now \
          ac-docker-firewall.service \
          ac-foundation-health.timer || rollback_failed=1
        if [[ -r /etc/systemd/system/ac-docker-firewall.timer ]]; then
          systemctl enable --now ac-docker-firewall.timer || rollback_failed=1
        fi
      else
        docker compose \
          --env-file "$release_dir/config/release/foundation-images.env" \
          -f "$release_dir/compose/foundation/compose.yaml" \
          down --remove-orphans --timeout 30 || rollback_failed=1
        systemctl disable --now ac-docker-firewall.timer ac-foundation-health.timer \
          >/dev/null 2>&1 || true
      fi
    fi
  fi

  if [[ "$rollback_failed" == 0 ]]; then
    printf 'ROLLBACK  Previous host and Compose state restored.\n' >&2
    return 0
  fi
  printf 'FAIL  Automatic release rollback was incomplete; use the pre-change host archive.\n' >&2
  return 1
}

cleanup() {
  local status=$?
  if [[ "$status" -ne 0 && "$transaction_active" == 1 && "$transaction_committed" == 0 ]]; then
    restore_failed_transaction || status=1
  fi
  if [[ -n "$stage_dir" && -e "$stage_dir" ]]; then
    case "$stage_dir" in
      "$releases_root"/.stage-*) rm -rf -- "$stage_dir" ;;
      *) printf 'Refusing to remove unexpected staging path: %s\n' "$stage_dir" >&2; status=1 ;;
    esac
  fi
  if [[ -n "$rollback_dir" && -e "$rollback_dir" ]]; then
    case "$rollback_dir" in
      /tmp/ac-release-rollback.*) rm -rf -- "$rollback_dir" ;;
      *) printf 'Refusing to remove unexpected rollback path: %s\n' "$rollback_dir" >&2; status=1 ;;
    esac
  fi
  exit "$status"
}
trap cleanup EXIT

begin_transaction() {
  local target previous_id
  local -a snapshot_paths
  rollback_dir="$(mktemp -d /tmp/ac-release-rollback.XXXXXX)"

  if [[ -L "$current_link" ]]; then
    previous_link_target="$(readlink "$current_link")"
    previous_release_dir="$(readlink -f "$current_link")"
    [[ "$(dirname "$previous_release_dir")" == "$releases_root" ]] || {
      printf 'Current release resolves outside the immutable release root.\n' >&2
      exit 1
    }
    previous_id="${previous_release_dir##*/}"
    if [[ "$test_mode" == 1 ]]; then
      [[ "$previous_id" =~ ^foundation-test-[a-z0-9-]+$ ]] || {
        printf 'Existing test release has an invalid identity: %s\n' "$previous_id" >&2
        exit 1
      }
      previous_release_mode=immutable
      [[ -f "$previous_release_dir/RELEASE-ID" && \
         "$(<"$previous_release_dir/RELEASE-ID")" == "$previous_id" ]]
      [[ -f "$previous_release_dir/RELEASE-COMMIT" && \
         "$(<"$previous_release_dir/RELEASE-COMMIT")" =~ ^[0-9a-f]{40}$ ]]
      [[ -r "$previous_release_dir/RELEASE-FILES.sha256" ]]
      (cd "$previous_release_dir" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
    elif [[ "$previous_id" =~ ^foundation-[0-9a-f]{40}$ ]]; then
      previous_release_mode=immutable
      [[ -f "$previous_release_dir/RELEASE-ID" && \
         "$(<"$previous_release_dir/RELEASE-ID")" == "$previous_id" ]]
      [[ -f "$previous_release_dir/RELEASE-COMMIT" && \
         "$(<"$previous_release_dir/RELEASE-COMMIT")" == "${previous_id#foundation-}" ]]
      [[ -r "$previous_release_dir/RELEASE-FILES.sha256" ]] || {
        printf 'Existing immutable foundation release lacks checksum evidence.\n' >&2
        exit 1
      }
      (cd "$previous_release_dir" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
    else
      previous_release_mode=legacy
      validate_legacy_foundation "$previous_id"
    fi
  elif [[ -e "$current_link" ]]; then
    printf 'Current release path exists but is not a symbolic link: %s\n' "$current_link" >&2
    exit 1
  fi

  snapshot_paths=()
  for target in "${transaction_targets[@]}"; do
    if [[ -e "$target" || -L "$target" ]]; then
      snapshot_paths+=("${target#/}")
    fi
  done
  if ((${#snapshot_paths[@]} > 0)); then
    tar --acls --xattrs --numeric-owner --directory=/ \
      --create --file="$rollback_dir/host-files.tar" "${snapshot_paths[@]}"
  else
    : > "$rollback_dir/host-files.tar"
  fi
  transaction_active=1
}

if [[ "$test_mode" == 1 ]]; then
  install -d -m 0750 "$srv_root" "$releases_root" "$application_root"
else
  install -d -m 2750 -o root -g acops "$srv_root" "$releases_root" "$application_root"
fi

# Application and foundation releases both own environment route selectors.
# One shared lock prevents either installer from validating stale selector
# state while the other changes Caddy mounts or links.
shared_release_lock="$application_root/.deployment.lock"
exec 9>>"$shared_release_lock"
if ! flock --exclusive --nonblock 9; then
  printf 'Another application deployment or foundation release is already active.\n' >&2
  exit 1
fi
if [[ "$test_mode" == 0 ]]; then
  chmod 0640 "$shared_release_lock"
  chown root:acops "$shared_release_lock"
fi

if [[ -e "$release_dir" ]]; then
  [[ -f "$release_dir/RELEASE-ID" && "$(<"$release_dir/RELEASE-ID")" == "$release_id" ]] || {
    printf 'Existing immutable release has invalid identity metadata: %s\n' "$release_dir" >&2
    exit 1
  }
  [[ -f "$release_dir/RELEASE-COMMIT" && "$(<"$release_dir/RELEASE-COMMIT")" == "$release_sha" ]] || {
    printf 'Existing immutable release has invalid commit metadata: %s\n' "$release_dir" >&2
    exit 1
  }
  (cd "$release_dir" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
else
  stage_dir="$(mktemp -d "$releases_root/.stage-${release_id}.XXXXXX")"
  if [[ -n "$release_archive" ]]; then
    python3 "$repo_root/scripts/verify-git-release-archive.py" \
      "$release_archive" "$release_archive_sha" "$release_sha"
    tar --extract --file="$release_archive" --directory="$stage_dir" --strip-components=2
    cmp --silent "$stage_dir/scripts/install-foundation-release.sh" "${BASH_SOURCE[0]}" || {
      printf 'Running installer differs from the checksum-verified release archive.\n' >&2
      exit 1
    }
  else
    git_root="$(git -C "$repo_root" rev-parse --show-toplevel 2>/dev/null)" || {
      printf 'Release source is not a Git checkout; provide a checksum-verified Git archive.\n' >&2
      exit 1
    }
    relative_repo_root="$(realpath --relative-to="$git_root" "$repo_root")"
    [[ "$relative_repo_root" != . && "$relative_repo_root" != ..* && "$relative_repo_root" != /* ]] || {
      printf 'Foundation source path is outside the Git worktree.\n' >&2
      exit 1
    }
    resolved_sha="$(git -C "$git_root" rev-parse --verify "${release_sha}^{commit}")"
    [[ "$resolved_sha" == "$release_sha" ]] || { printf 'Release commit does not resolve exactly.\n' >&2; exit 1; }
    [[ "$(git -C "$git_root" rev-parse HEAD)" == "$release_sha" ]] || {
      printf 'Checked-out HEAD does not match the requested release commit.\n' >&2
      exit 1
    }
    if ! git -C "$git_root" diff --quiet "$release_sha" -- "$relative_repo_root/scripts/install-foundation-release.sh"; then
      printf 'Running installer differs from the requested release commit.\n' >&2
      exit 1
    fi
    strip_components="$(awk -F/ '{print NF}' <<<"$relative_repo_root")"
    git -C "$git_root" archive --format=tar "$release_sha" -- "$relative_repo_root" \
      | tar --extract --file=- --directory="$stage_dir" --strip-components="$strip_components"
  fi
  if find "$stage_dir" -type l -print -quit | grep -q .; then
    printf 'Exact-commit release archive contains a symbolic link; refusing ambiguous packaging.\n' >&2
    exit 1
  fi
  printf '%s\n' "$release_id" > "$stage_dir/RELEASE-ID"
  printf '%s\n' "$release_sha" > "$stage_dir/RELEASE-COMMIT"
  (
    cd "$stage_dir"
    mapfile -d '' -t release_files < <(find . -type f -print0 | LC_ALL=C sort -z)
    : > RELEASE-FILES.sha256
    for release_file in "${release_files[@]}"; do
      sha256sum "$release_file" >> RELEASE-FILES.sha256
    done
    sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null
  )
  find "$stage_dir" -type d -exec chmod 0750 {} +
  find "$stage_dir" -type f -exec chmod 0640 {} +
  chmod 0644 \
    "$stage_dir/compose/foundation/Caddyfile" \
    "$stage_dir/compose/foundation/otel-collector.yaml" \
    "$stage_dir/compose/foundation/application-routes/production.caddy" \
    "$stage_dir/compose/foundation/application-routes/staging.caddy"
  find "$stage_dir/scripts" -type f -exec chmod 0750 {} +
  if [[ "$test_mode" == 0 ]]; then
    chown -R root:acops "$stage_dir"
  fi
  mv -- "$stage_dir" "$release_dir"
  stage_dir=''
fi

manifest="$release_dir/config/release/install-manifest.tsv"
[[ -r "$manifest" ]] || { printf 'Released install manifest is not readable: %s\n' "$manifest" >&2; exit 1; }
declare -A installed_targets=()
declare -a install_sources=() install_targets=()
declare -a install_modes=() install_owners=() install_groups=()
while IFS=$'\t' read -r kind source target mode owner group; do
  [[ -z "$kind" || "$kind" == \#* ]] && continue
  [[ "$kind" == executable || "$kind" == unit ]] || {
    printf 'Unsupported install kind: %s\n' "$kind" >&2
    exit 1
  }
  [[ "$source" != /* && "$source" != *'..'* ]] || {
    printf 'Unsafe release source path: %s\n' "$source" >&2
    exit 1
  }
  case "$target" in
    /usr/local/sbin/ac-*|/usr/local/libexec/authority-closers/*|/etc/systemd/system/ac-*|/etc/systemd/system/cloudflared.service) ;;
    *) printf 'Install target is outside the approved paths: %s\n' "$target" >&2; exit 1 ;;
  esac
  [[ "$mode" =~ ^0[467][0-7]{2}$ ]] || { printf 'Invalid install mode for %s.\n' "$target" >&2; exit 1; }
  [[ "$owner" == root && "$group" == root ]] || {
    printf 'Install ownership must be root:root for %s.\n' "$target" >&2
    exit 1
  }
  [[ -z "${installed_targets[$target]:-}" ]] || {
    printf 'Duplicate install target: %s\n' "$target" >&2
    exit 1
  }
  installed_targets[$target]=1
  source_path="$release_dir/$source"
  [[ -f "$source_path" ]] || { printf 'Manifest source is missing: %s\n' "$source" >&2; exit 1; }
  install_sources+=("$source")
  install_targets+=("$target")
  install_modes+=("$mode")
  install_owners+=("$owner")
  install_groups+=("$group")
  transaction_targets+=("${install_root}${target}")
done < "$manifest"

((${#install_targets[@]} > 0)) || { printf 'Released install manifest is empty.\n' >&2; exit 1; }
if [[ "$test_mode" == 0 ]]; then
  AC_BASELINE_POLICY_DIR="$release_dir/config/release" \
    "$release_dir/scripts/ac-os-baseline-verify"
  transaction_targets+=(
    /usr/local/bin/infisical
    /usr/local/bin/rclone
    "/var/lib/authority-closers/toolchains/${release_id}.env"
  )
fi

if [[ -e "$application_edge_route_releases_root" || -L "$application_edge_route_releases_root" ]]; then
  [[ -d "$application_edge_route_releases_root" && \
     ! -L "$application_edge_route_releases_root" ]] || {
    printf 'Application edge-route projection root is not a real directory.\n' >&2
    exit 1
  }
fi
install -d -m 0755 "$application_edge_route_releases_root"
# A setgid application parent makes GNU install inherit the setgid bit. Keep
# this projection boundary an ordinary root-owned 755 directory so later
# release projections and selectors are validated against the intended mode.
chmod 0755 "$application_edge_route_releases_root"
chmod a-s "$application_edge_route_releases_root"
if [[ "$test_mode" == 0 ]]; then
  chown root:root "$application_edge_route_releases_root"
  [[ "$(stat -c '%U:%G %a' "$application_edge_route_releases_root")" == 'root:root 755' ]]
else
  [[ "$(stat -c '%a' "$application_edge_route_releases_root")" == 755 ]]
fi
if [[ ! -e "$foundation_edge_route_projection" && ! -L "$foundation_edge_route_projection" ]]; then
  projection_stage="$(mktemp -d "$application_edge_route_releases_root/.${release_id}.XXXXXX")"
  for route_environment in production staging; do
    install -m 0444 \
      "$release_dir/compose/foundation/application-routes/$route_environment.caddy" \
      "$projection_stage/$route_environment.caddy"
  done
  chmod 0755 "$projection_stage"
  if [[ "$test_mode" == 0 ]]; then
    chown -R root:root "$projection_stage"
  fi
  mv --no-target-directory --no-clobber "$projection_stage" \
    "$foundation_edge_route_projection"
elif [[ ! -d "$foundation_edge_route_projection" || -L "$foundation_edge_route_projection" ]]; then
  printf 'Foundation edge-route projection is not a real directory.\n' >&2
  exit 1
fi
if [[ "$test_mode" == 0 ]]; then
  [[ "$(stat -c '%U:%G %a' "$foundation_edge_route_projection")" == 'root:root 755' ]]
else
  [[ "$(stat -c '%a' "$foundation_edge_route_projection")" == 755 ]]
fi
mapfile -t foundation_projection_files < <(
  find "$foundation_edge_route_projection" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort
)
[[ "${foundation_projection_files[*]}" == 'production.caddy staging.caddy' ]] || {
  printf 'Foundation edge-route projection has an unexpected file set.\n' >&2
  exit 1
}
for route_environment in production staging; do
  projection_file="$foundation_edge_route_projection/$route_environment.caddy"
  [[ -f "$projection_file" && ! -L "$projection_file" ]]
  [[ "$(stat -c '%a' "$projection_file")" == 444 ]]
  if [[ "$test_mode" == 0 ]]; then
    [[ "$(stat -c '%U:%G' "$projection_file")" == root:root ]]
  fi
  cmp --silent \
    "$release_dir/compose/foundation/application-routes/$route_environment.caddy" \
    "$projection_file"
done

validate_edge_route_selector() {
  local route_environment="$1" route_selector="$2" route_target projection_id
  local owner_release expected_source
  [[ -L "$route_selector" ]] || return 1
  route_target="$(readlink -f "$route_selector")"
  [[ -f "$route_target" && ! -L "$route_target" ]] || return 1
  projection_id="$(basename "$(dirname "$route_target")")"
  case "$route_target" in
    "$application_edge_route_releases_root"/foundation-*/"$route_environment".caddy)
      if [[ "$test_mode" == 1 ]]; then
        [[ "$projection_id" =~ ^foundation-(test-[a-z0-9-]+|[0-9a-f]{40})$ ]] || return 1
      else
        [[ "$projection_id" =~ ^foundation-[0-9a-f]{40}$ ]] || return 1
      fi
      owner_release="$releases_root/$projection_id"
      expected_source="$owner_release/compose/foundation/application-routes/$route_environment.caddy"
      ;;
    "$application_edge_route_releases_root"/[0-9a-f]*/"$route_environment".caddy|\
    "$application_edge_route_releases_root"/[0-9a-f]*/"$route_environment"-hold.caddy)
      [[ "$projection_id" =~ ^[0-9a-f]{40}$ ]] || return 1
      owner_release="$application_root/releases/$projection_id"
      expected_source="$owner_release/edge-routes/$(basename "$route_target")"
      ;;
    *) return 1 ;;
  esac
  [[ -f "$owner_release/RELEASE-ID" || -f "$owner_release/RELEASE-COMMIT" ]] || return 1
  if [[ "$projection_id" == foundation-* ]]; then
    [[ -f "$owner_release/RELEASE-ID" && "$(<"$owner_release/RELEASE-ID")" == "$projection_id" ]]
    if [[ "$test_mode" == 1 && "$projection_id" == foundation-test-* ]]; then
      [[ -f "$owner_release/RELEASE-COMMIT" && "$(<"$owner_release/RELEASE-COMMIT")" =~ ^[0-9a-f]{40}$ ]]
    else
      [[ -f "$owner_release/RELEASE-COMMIT" && \
         "$(<"$owner_release/RELEASE-COMMIT")" == "${projection_id#foundation-}" ]]
    fi
  else
    [[ -f "$owner_release/RELEASE-COMMIT" && "$(<"$owner_release/RELEASE-COMMIT")" == "$projection_id" ]]
  fi
  (cd "$owner_release" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
  [[ -f "$expected_source" && ! -L "$expected_source" ]]
  [[ "$(stat -c '%a' "$route_target")" == 444 ]]
  if [[ "$test_mode" == 0 ]]; then
    [[ "$(stat -c '%U:%G' "$route_target")" == root:root ]]
  fi
  cmp --silent "$expected_source" "$route_target"
}

declare -A foundation_owned_selectors=()
if [[ -e "$application_edge_routes_root" || -L "$application_edge_routes_root" ]]; then
  [[ -d "$application_edge_routes_root" && ! -L "$application_edge_routes_root" ]] || {
    printf 'Application edge-route selector root is not a real directory.\n' >&2
    exit 1
  }
  selector_root_mode="$(stat -c '%a' "$application_edge_routes_root")"
  [[ "$selector_root_mode" == 755 || "$selector_root_mode" == 2755 ]] || {
    printf 'Application edge-route selector root has unexpected mode.\n' >&2
    exit 1
  }
  if [[ "$test_mode" == 0 ]]; then
    [[ "$(stat -c '%U:%G' "$application_edge_routes_root")" == 'root:root' ]] || {
      printf 'Application edge-route selector root has unexpected ownership or mode.\n' >&2
      exit 1
    }
  fi
fi
for route_environment in production staging; do
  route_selector="$application_edge_routes_root/$route_environment.caddy"
  transaction_targets+=("$route_selector")
  if [[ -e "$route_selector" || -L "$route_selector" ]]; then
    [[ -L "$route_selector" ]] || {
      printf 'Application edge-route selector is not a symbolic link: %s\n' "$route_selector" >&2
      exit 1
    }
    validate_edge_route_selector "$route_environment" "$route_selector" || {
      printf 'Application edge-route selector is not bound to a verified immutable release.\n' >&2
      exit 1
    }
    route_target="$(readlink -f "$route_selector")"
    route_projection_id="$(basename "$(dirname "$route_target")")"
    if [[ "$route_projection_id" == foundation-* ]]; then
      foundation_owned_selectors[$route_environment]=1
    fi
  fi
done
begin_transaction

if [[ ! -d "$application_edge_routes_root" ]]; then
  if [[ "$test_mode" == 1 ]]; then
    install -d -m 0755 "$application_edge_routes_root"
  else
    install -d -m 0755 -o root -g root "$application_edge_routes_root"
  fi
  application_edge_routes_root_created=1
fi
# The selector root can also inherit setgid when it is first created beneath
# the application root; normalize it before its exact mode is enforced.
chmod 0755 "$application_edge_routes_root"
chmod a-s "$application_edge_routes_root"
if [[ "$test_mode" == 0 ]]; then
  [[ "$(stat -c '%U:%G %a' "$application_edge_routes_root")" == 'root:root 755' ]] || {
    printf 'Application edge-route selector root has unexpected ownership or mode.\n' >&2
    exit 1
  }
fi
for route_environment in production staging; do
  route_selector="$application_edge_routes_root/$route_environment.caddy"
  if [[ ! -L "$route_selector" || \
        "${foundation_owned_selectors[$route_environment]:-0}" == 1 ]]; then
    route_selector_tmp="$application_edge_routes_root/.${route_environment}-${release_id}.$$"
    ln -s "$foundation_edge_route_projection/$route_environment.caddy" \
      "$route_selector_tmp"
    mv --no-target-directory --force "$route_selector_tmp" "$route_selector"
  fi
done

if [[ "$test_mode" == 0 ]]; then
  AC_RELEASE_ID="$release_id" \
  AC_TOOLCHAIN_POLICY="$release_dir/config/release/toolchain.env" \
    "$release_dir/scripts/install-pinned-toolchain.sh"
fi

for index in "${!install_targets[@]}"; do
  source="${install_sources[$index]}"
  target="${install_targets[$index]}"
  mode="${install_modes[$index]}"
  owner="${install_owners[$index]}"
  group="${install_groups[$index]}"
  source_path="$release_dir/$source"
  destination="${install_root}${target}"
  install -d -m 0755 "$(dirname "$destination")"
  if [[ "$test_mode" == 1 ]]; then
    install -m "$mode" "$source_path" "$destination"
  else
    install -o "$owner" -g "$group" -m "$mode" "$source_path" "$destination"
  fi
  cmp --silent "$source_path" "$destination" || {
    printf 'Installed file differs from release source: %s\n' "$target" >&2
    exit 1
  }
  [[ "$(stat -c '%a' "$destination")" == "${mode#0}" ]] || {
    printf 'Installed mode differs from manifest for %s.\n' "$target" >&2
    exit 1
  }
done

if [[ "$test_fail_after_install" == 1 ]]; then
  printf 'TEST  Injecting a post-install failure.\n' >&2
  exit 97
fi

activate_current_release() {
  local current_tmp
  if [[ -e "$current_link" && ! -L "$current_link" ]]; then
    printf 'Current release path exists but is not a symbolic link: %s\n' "$current_link" >&2
    exit 1
  fi
  current_tmp="$srv_root/.current-${release_id}.$$"
  ln -s "$release_dir" "$current_tmp"
  mv --no-target-directory --force "$current_tmp" "$current_link"
  [[ "$(readlink -f "$current_link")" == "$release_dir" ]] || {
    printf 'Current release link verification failed.\n' >&2
    exit 1
  }
}

if [[ "$test_mode" == 0 ]]; then
  systemctl daemon-reload
  compose_mutated=1
  reconcile_compose_release "$release_dir"
  /usr/local/sbin/ac-docker-firewall
  activate_current_release
  systemctl enable --now \
    ac-docker-firewall.service \
    ac-docker-firewall.timer \
    ac-foundation-health.timer
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/healthz >/dev/null
else
  activate_current_release
fi
if [[ "$test_fail_after_activate" == 1 ]]; then
  printf 'TEST  Injecting a post-activation failure.\n' >&2
  exit 98
fi
transaction_committed=1

printf 'PASS  Installed and reconciled immutable foundation release %s with %s managed host files.\n' \
  "$release_id" "${#installed_targets[@]}"
