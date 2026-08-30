#!/usr/bin/env bash
set -euo pipefail

target_environment="${AC_TARGET_ENVIRONMENT:-}"
release_id="${AC_RELEASE_ID:-}"
release_archive="${AC_RELEASE_ARCHIVE:-}"
release_archive_sha256="${AC_RELEASE_ARCHIVE_SHA256:-}"
image_bundle_dir="${AC_IMAGE_BUNDLE_DIR:-}"
secret_path="${AC_INFISICAL_PATH:-/application}"

[[ "$(id -u)" -eq 0 ]] || { printf 'Run as root.\n' >&2; exit 1; }
[[ "$target_environment" == staging || "$target_environment" == production ]] || {
  printf 'AC_TARGET_ENVIRONMENT must be staging or production.\n' >&2
  exit 2
}
[[ "$release_id" =~ ^[0-9a-f]{40}$ ]] || {
  printf 'AC_RELEASE_ID must be a full lowercase Git commit SHA.\n' >&2
  exit 2
}
[[ "$release_archive" == /* && -f "$release_archive" ]] || {
  printf 'AC_RELEASE_ARCHIVE must be an absolute regular file.\n' >&2
  exit 2
}
[[ "$release_archive_sha256" =~ ^[0-9a-f]{64}$ ]] || {
  printf 'AC_RELEASE_ARCHIVE_SHA256 is malformed.\n' >&2
  exit 2
}
[[ "$image_bundle_dir" == /* && -d "$image_bundle_dir" && ! -L "$image_bundle_dir" ]] || {
  printf 'AC_IMAGE_BUNDLE_DIR must be an absolute directory.\n' >&2
  exit 2
}
[[ "$secret_path" == /* && "$secret_path" != *'..'* ]] || {
  printf 'AC_INFISICAL_PATH must be absolute and traversal-free.\n' >&2
  exit 2
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$script_dir/verify-release-archive.py" \
  "$release_archive" "$release_archive_sha256" "$release_id"

expected_bundle_files=(
  SHA256SUMS
  application-images.tar.gz
  release-images.env
)
mapfile -t actual_bundle_files < <(
  find "$image_bundle_dir" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort
)
[[ "${actual_bundle_files[*]}" == "${expected_bundle_files[*]}" ]] || {
  printf 'Image bundle does not contain the exact reviewed file set.\n' >&2
  exit 1
}
if find "$image_bundle_dir" -mindepth 1 -maxdepth 1 ! -type f -print -quit | grep -q .; then
  printf 'Image bundle contains a non-regular entry.\n' >&2
  exit 1
fi

declare -A expected_checksums=()
while read -r checksum filename; do
  [[ "$checksum" =~ ^[0-9a-f]{64}$ ]] || { printf 'Malformed bundle checksum.\n' >&2; exit 1; }
  case "$filename" in
    application-images.tar.gz|release-images.env) ;;
    *) printf 'Unexpected path in bundle checksum manifest: %s\n' "$filename" >&2; exit 1 ;;
  esac
  [[ -z "${expected_checksums[$filename]:-}" ]] || {
    printf 'Duplicate bundle checksum entry: %s\n' "$filename" >&2
    exit 1
  }
  expected_checksums[$filename]="$checksum"
done < "$image_bundle_dir/SHA256SUMS"
[[ "${#expected_checksums[@]}" -eq 2 ]] || {
  printf 'Bundle checksum manifest is incomplete.\n' >&2
  exit 1
}
for filename in "${!expected_checksums[@]}"; do
  actual_checksum="$(sha256sum "$image_bundle_dir/$filename" | awk '{print $1}')"
  [[ "$actual_checksum" == "${expected_checksums[$filename]}" ]] || {
    printf 'Bundle checksum mismatch: %s\n' "$filename" >&2
    exit 1
  }
done

release_images_file="$image_bundle_dir/release-images.env"
expected_image_keys=(
  AC_ADMIN_IMAGE
  AC_ADMIN_REGISTRY_DIGEST
  AC_API_IMAGE
  AC_API_REGISTRY_DIGEST
  AC_LEARNER_IMAGE
  AC_LEARNER_REGISTRY_DIGEST
  AC_RELEASE_ID
)
mapfile -t actual_image_keys < <(
  sed -n 's/^\([A-Z0-9_]\+\)=.*/\1/p' "$release_images_file" | LC_ALL=C sort
)
[[ "${actual_image_keys[*]}" == "${expected_image_keys[*]}" ]] || {
  printf 'Release image manifest has an unexpected key set.\n' >&2
  exit 1
}
if grep -Ev '^[A-Z0-9_]+=[A-Za-z0-9./:@_-]+$' "$release_images_file" | grep -q .; then
  printf 'Release image manifest contains unsafe syntax.\n' >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$release_images_file"
set +a
[[ "$AC_RELEASE_ID" == "$release_id" ]] || {
  printf 'Image bundle release ID does not match the source release.\n' >&2
  exit 1
}
for image_id in "$AC_API_IMAGE" "$AC_LEARNER_IMAGE" "$AC_ADMIN_IMAGE"; do
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    printf 'Application deployment requires exact OCI transport manifest digests.\n' >&2
    exit 1
  }
done
for registry_digest in \
  "$AC_API_REGISTRY_DIGEST" "$AC_LEARNER_REGISTRY_DIGEST" "$AC_ADMIN_REGISTRY_DIGEST"; do
  [[ "$registry_digest" =~ ^ghcr\.io/authorityclosers/[a-z0-9-]+@sha256:[0-9a-f]{64}$ ]] || {
    printf 'Application registry provenance digest is malformed.\n' >&2
    exit 1
  }
done

getent group acops >/dev/null || { printf 'Required operator group acops is absent.\n' >&2; exit 1; }
application_root=/srv/authority-closers/application
releases_root="$application_root/releases"
release_dir="$releases_root/$release_id"
current_link="$application_root/current-$target_environment"
stage_dir=''
artifact_stage=''
install -d -m 2750 -o root -g acops "$application_root" "$releases_root"

artifacts_root="$application_root/artifacts"
artifact_dir="$artifacts_root/$release_id"
install -d -m 2750 -o root -g acops "$artifacts_root"

cleanup_stage() {
  local status=$?
  if [[ -n "$stage_dir" && -e "$stage_dir" ]]; then
    case "$stage_dir" in
      "$releases_root"/.stage-*) rm -rf -- "$stage_dir" ;;
      *) printf 'Refusing unexpected staging cleanup path: %s\n' "$stage_dir" >&2; status=1 ;;
    esac
  fi
  if [[ -n "$artifact_stage" && -e "$artifact_stage" ]]; then
    case "$artifact_stage" in
      "$artifacts_root"/.stage-*) rm -rf -- "$artifact_stage" ;;
      *) printf 'Refusing unexpected artifact cleanup path: %s\n' "$artifact_stage" >&2; status=1 ;;
    esac
  fi
  return "$status"
}
trap cleanup_stage EXIT

if [[ -e "$artifact_dir" ]]; then
  [[ -d "$artifact_dir" && ! -L "$artifact_dir" ]] || {
    printf 'Existing release artifact path is not a directory.\n' >&2
    exit 1
  }
  for filename in "${expected_bundle_files[@]}"; do
    cmp --silent "$artifact_dir/$filename" "$image_bundle_dir/$filename" || {
      printf 'Existing immutable image artifact differs: %s\n' "$filename" >&2
      exit 1
    }
  done
else
  artifact_stage="$(mktemp -d "$artifacts_root/.stage-${release_id}.XXXXXX")"
  for filename in "${expected_bundle_files[@]}"; do
    cp -- "$image_bundle_dir/$filename" "$artifact_stage/$filename"
  done
  find "$artifact_stage" -type d -exec chmod 0750 {} +
  find "$artifact_stage" -type f -exec chmod 0640 {} +
  chown -R root:acops "$artifact_stage"
  mv -- "$artifact_stage" "$artifact_dir"
  artifact_stage=''
fi
image_bundle_dir="$artifact_dir"

if [[ -e "$release_dir" ]]; then
  [[ -f "$release_dir/RELEASE-COMMIT" && "$(<"$release_dir/RELEASE-COMMIT")" == "$release_id" ]]
  (cd "$release_dir" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
  cmp --silent "$release_dir/release-images.env" "$release_images_file" || {
    printf 'Existing immutable release has different image provenance.\n' >&2
    exit 1
  }
else
  stage_dir="$(mktemp -d "$releases_root/.stage-${release_id}.XXXXXX")"
  tar --extract --file="$release_archive" --directory="$stage_dir" --strip-components=2
  cmp --silent "$stage_dir/scripts/install-application-release.sh" "${BASH_SOURCE[0]}" || {
    printf 'Running installer differs from the verified archive.\n' >&2
    exit 1
  }
  cp -- "$release_images_file" "$stage_dir/release-images.env"
  printf '%s\n' "$release_id" > "$stage_dir/RELEASE-COMMIT"
  (
    cd "$stage_dir"
    mapfile -d '' -t release_files < <(find . -type f ! -name RELEASE-FILES.sha256 -print0 | LC_ALL=C sort -z)
    : > RELEASE-FILES.sha256
    for release_file in "${release_files[@]}"; do
      sha256sum "$release_file" >> RELEASE-FILES.sha256
    done
    sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null
  )
  find "$stage_dir" -type d -exec chmod 0750 {} +
  find "$stage_dir" -type f -exec chmod 0640 {} +
  # The non-root PostgreSQL process consumes this bind-mounted bootstrap tree.
  # It contains no credentials; passwords arrive only through Infisical-backed
  # environment variables at container start.
  find "$stage_dir/postgres/init" -type d -exec chmod 0755 {} +
  find "$stage_dir/postgres/init" -type f -exec chmod 0644 {} +
  find "$stage_dir/scripts" -type f -exec chmod 0750 {} +
  chown -R root:acops "$stage_dir"
  mv -- "$stage_dir" "$release_dir"
  stage_dir=''
fi

gzip --decompress --stdout "$image_bundle_dir/application-images.tar.gz" | docker load >/dev/null
for image_id in "$AC_API_IMAGE" "$AC_LEARNER_IMAGE" "$AC_ADMIN_IMAGE"; do
  [[ "$(docker image inspect --format '{{.Id}}' "$image_id")" == "$image_id" ]] || {
    printf 'Loaded image identity verification failed: %s\n' "$image_id" >&2
    exit 1
  }
done

profile_file="$release_dir/environments/$target_environment.env"
secret_environment="$target_environment"
[[ "$target_environment" == production ]] && secret_environment=prod
if LC_ALL=C grep -q $'\r' "$profile_file"; then
  printf 'Released environment profile must use canonical LF line endings.\n' >&2
  exit 1
fi
state_root="$(sed -n 's/^AC_STATE_ROOT=//p' "$profile_file")"
[[ "$state_root" == "/srv/authority-closers/state/application/$target_environment" ]] || {
  printf 'Released state root does not match the target environment.\n' >&2
  exit 1
}
install -d -m 0750 -o root -g acops "$state_root"
install -d -m 0700 -o 999 -g 999 "$state_root/postgres"

compose_for() {
  local target_release="$1"
  shift
  AC_INFISICAL_ENVIRONMENT="$secret_environment" \
  AC_INFISICAL_PATH="$secret_path" \
    /usr/local/sbin/ac-infisical-run -- \
      env \
        -u AC_COMPOSE_PROJECT \
        -u AC_ENVIRONMENT \
        -u AC_STATE_ROOT \
        -u AC_PUBLIC_APP_URL \
        -u AC_ADMIN_APP_URL \
        -u AC_API_URL \
        -u AC_API_HOST \
        -u AC_EDGE_API_ALIAS \
        -u AC_EDGE_LEARNER_ALIAS \
        -u AC_EDGE_ADMIN_ALIAS \
        -u AC_EXTERNAL_SIDE_EFFECTS_HOLD \
        -u AC_EMAIL_PROVIDER \
        -u AC_RELEASE_ID \
        -u AC_API_IMAGE \
        -u AC_LEARNER_IMAGE \
        -u AC_ADMIN_IMAGE \
      docker compose \
        --env-file "$target_release/environments/$target_environment.env" \
        --env-file "$target_release/release-images.env" \
        --file "$target_release/compose.yaml" \
        "$@"
}

compose_for "$release_dir" config --quiet
previous_release=''
if [[ -L "$current_link" ]]; then
  previous_release="$(readlink -f "$current_link")"
  [[ "$(dirname "$previous_release")" == "$releases_root" ]] || {
    printf 'Current application release resolves outside its immutable root.\n' >&2
    exit 1
  }
  (cd "$previous_release" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
elif [[ -e "$current_link" ]]; then
  printf 'Current application release path is not a symbolic link.\n' >&2
  exit 1
fi

backup_root="/srv/authority-closers/backups/application/$target_environment"
install -d -m 0750 -o root -g acops "$backup_root"
backup_file="$backup_root/$(date -u +%Y%m%dT%H%M%SZ)-pre-${release_id}.dump"
mutation_started=0
backup_ready=0
release_committed=0

rollback_release() {
  local rollback_failed=0
  printf 'ROLLBACK  Restoring %s after failed release %s.\n' "$target_environment" "$release_id" >&2
  compose_for "$release_dir" stop api worker learner-web admin-web >/dev/null 2>&1 || rollback_failed=1
  if [[ "$backup_ready" == 1 ]]; then
    # shellcheck disable=SC2016  # PostgreSQL container variables expand inside `sh -euc`.
    if ! compose_for "$release_dir" exec -T postgres sh -euc '
      export PGPASSWORD="$POSTGRES_PASSWORD"
      psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''$POSTGRES_DB'\'' AND pid <> pg_backend_pid()"
      pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres \
        --clean --if-exists --create --exit-on-error
    ' < "$backup_file"; then
      rollback_failed=1
    fi
  fi
  if [[ -n "$previous_release" ]]; then
    compose_for "$previous_release" up --detach --remove-orphans --wait --wait-timeout 180 \
      || rollback_failed=1
  else
    compose_for "$release_dir" down --remove-orphans --timeout 30 || rollback_failed=1
  fi
  [[ "$rollback_failed" == 0 ]] || {
    printf 'FAIL  Automatic application rollback was incomplete.\n' >&2
    return 1
  }
  printf 'ROLLBACK  Database and previous application release restored.\n' >&2
}

finish() {
  local status=$?
  if [[ "$status" -ne 0 && "$mutation_started" == 1 && "$release_committed" == 0 ]]; then
    rollback_release || status=1
  fi
  exit "$status"
}
trap finish EXIT

mutation_started=1
compose_for "$release_dir" up --detach --wait --wait-timeout 180 postgres
umask 077
# shellcheck disable=SC2016  # Backup credentials and database name expand only in the container.
compose_for "$release_dir" exec -T postgres sh -euc '
  export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"
  pg_dump -h 127.0.0.1 -U ac_backup -d "$POSTGRES_DB" --format=custom --create
' > "$backup_file"
compose_for "$release_dir" exec -T postgres pg_restore --list < "$backup_file" >/dev/null
backup_ready=1

compose_for "$release_dir" --profile release run --rm migrate
compose_for "$release_dir" up --detach --remove-orphans --wait --wait-timeout 180 \
  api worker learner-web admin-web

profile_value() {
  sed -n "s/^$1=//p" "$profile_file"
}
learner_host="$(profile_value AC_PUBLIC_APP_URL)"
learner_host="${learner_host#https://}"
admin_host="$(profile_value AC_ADMIN_APP_URL)"
admin_host="${admin_host#https://}"
api_host="$(profile_value AC_API_HOST)"

check_route() {
  local host="$1" path="$2" expected_status="$3" expected_route="$4"
  local headers body status
  headers="$(mktemp /tmp/ac-route-headers.XXXXXX)"
  body="$(mktemp /tmp/ac-route-body.XXXXXX)"
  status="$(curl --silent --show-error --max-time 10 \
    --header "Host: $host" --dump-header "$headers" --output "$body" \
    --write-out '%{http_code}' "http://127.0.0.1:8080$path")"
  if [[ "$status" != "$expected_status" ]] || \
    ! grep -qi "^X-Authority-Closers-Route: $expected_route" "$headers"; then
    rm -f -- "$headers" "$body"
    printf 'Route validation failed for %s%s.\n' "$host" "$path" >&2
    return 1
  fi
  rm -f -- "$headers" "$body"
}

check_route "$learner_host" / 200 "learner-$target_environment"
check_route "$admin_host" / 403 "admin-$target_environment"
check_route "$api_host" /health/ready 200 "api-$target_environment"

current_tmp="$application_root/.current-${target_environment}-${release_id}.$$"
ln -s "$release_dir" "$current_tmp"
mv --no-target-directory --force "$current_tmp" "$current_link"
[[ "$(readlink -f "$current_link")" == "$release_dir" ]]

evidence_root="$application_root/deployments/$target_environment"
install -d -m 0750 -o root -g acops "$evidence_root"
evidence_file="$evidence_root/$(date -u +%Y%m%dT%H%M%SZ)-${release_id}.env"
{
  printf 'AC_ENVIRONMENT=%s\n' "$target_environment"
  printf 'AC_RELEASE_ID=%s\n' "$release_id"
  printf 'AC_PREVIOUS_RELEASE=%s\n' "${previous_release##*/}"
  printf 'AC_PRE_MIGRATION_BACKUP=%s\n' "$backup_file"
  printf 'AC_API_IMAGE=%s\n' "$AC_API_IMAGE"
  printf 'AC_API_REGISTRY_DIGEST=%s\n' "$AC_API_REGISTRY_DIGEST"
  printf 'AC_LEARNER_IMAGE=%s\n' "$AC_LEARNER_IMAGE"
  printf 'AC_LEARNER_REGISTRY_DIGEST=%s\n' "$AC_LEARNER_REGISTRY_DIGEST"
  printf 'AC_ADMIN_IMAGE=%s\n' "$AC_ADMIN_IMAGE"
  printf 'AC_ADMIN_REGISTRY_DIGEST=%s\n' "$AC_ADMIN_REGISTRY_DIGEST"
} > "$evidence_file"
chmod 0640 "$evidence_file"
chown root:acops "$evidence_file"
release_committed=1

printf 'PASS  %s now runs exact release %s with held external side effects.\n' \
  "$target_environment" "$release_id"
