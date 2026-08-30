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
[[ "$release_archive" == /* && -f "$release_archive" && ! -L "$release_archive" ]] || {
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
getent group acops >/dev/null || { printf 'Required operator group acops is absent.\n' >&2; exit 1; }
application_root=/srv/authority-closers/application
releases_root="$application_root/releases"
release_dir="$releases_root/$release_id"
current_link="$application_root/current-$target_environment"
input_stage=''
stage_dir=''
artifact_stage=''
install -d -m 2750 -o root -g acops "$application_root" "$releases_root"

# One installer at a time protects the shared immutable artifact/release stores
# as well as each environment's current link and rollback baseline. The lock is
# held by this file descriptor until the process exits.
deployment_lock="$application_root/.deployment.lock"
exec 9>>"$deployment_lock"
if ! flock --exclusive --nonblock 9; then
  printf 'Another application deployment is already active.\n' >&2
  exit 1
fi
chmod 0640 "$deployment_lock"
chown root:acops "$deployment_lock"

artifacts_root="$application_root/artifacts"
artifact_dir="$artifacts_root/$release_id"
install -d -m 2750 -o root -g acops "$artifacts_root"

cleanup_stages() {
  local cleanup_failed=0
  if [[ -n "$input_stage" && ( -e "$input_stage" || -L "$input_stage" ) ]]; then
    case "$input_stage" in
      "$application_root"/.inputs-*)
        rm -rf -- "$input_stage" || cleanup_failed=1
        [[ ! -e "$input_stage" && ! -L "$input_stage" ]] || cleanup_failed=1
        ;;
      *) printf 'Refusing unexpected input staging cleanup path: %s\n' "$input_stage" >&2; cleanup_failed=1 ;;
    esac
  fi
  if [[ -n "$stage_dir" && ( -e "$stage_dir" || -L "$stage_dir" ) ]]; then
    case "$stage_dir" in
      "$releases_root"/.stage-*)
        rm -rf -- "$stage_dir" || cleanup_failed=1
        [[ ! -e "$stage_dir" && ! -L "$stage_dir" ]] || cleanup_failed=1
        ;;
      *) printf 'Refusing unexpected staging cleanup path: %s\n' "$stage_dir" >&2; cleanup_failed=1 ;;
    esac
  fi
  if [[ -n "$artifact_stage" && ( -e "$artifact_stage" || -L "$artifact_stage" ) ]]; then
    case "$artifact_stage" in
      "$artifacts_root"/.stage-*)
        rm -rf -- "$artifact_stage" || cleanup_failed=1
        [[ ! -e "$artifact_stage" && ! -L "$artifact_stage" ]] || cleanup_failed=1
        ;;
      *) printf 'Refusing unexpected artifact cleanup path: %s\n' "$artifact_stage" >&2; cleanup_failed=1 ;;
    esac
  fi
  return "$cleanup_failed"
}

finish_before_mutation() {
  local status=$?
  trap '' HUP INT TERM
  trap - EXIT
  if ! cleanup_stages; then
    [[ "$status" -ne 0 ]] || status=1
  fi
  exit "$status"
}
trap finish_before_mutation EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

input_stage="$(mktemp -d "$application_root/.inputs-${release_id}.XXXXXX")"
# GNU chmod preserves an inherited setgid bit on directories unless the
# numeric mode explicitly includes the special-bit digit. The application
# root is intentionally setgid, so use 00700 to make this private boundary
# exactly 0700 before the Python verifier inspects it.
chmod 00700 "$input_stage"
chown root:root "$input_stage"
python3 "$script_dir/prepare-release-inputs.py" stage \
  "$release_archive" "$image_bundle_dir" "$input_stage"
release_archive="$input_stage/release-archive.tar"
image_bundle_dir="$input_stage/image-bundle"

python3 "$script_dir/verify-release-archive.py" \
  "$release_archive" "$release_archive_sha256" "$release_id"

manifest_values_file="$input_stage/release-image-values"
umask 077
python3 "$script_dir/prepare-release-inputs.py" verify-bundle \
  "$image_bundle_dir" "$release_id" > "$manifest_values_file"
mapfile -t release_image_values < "$manifest_values_file"
rm -- "$manifest_values_file"
[[ "${#release_image_values[@]}" -eq 11 ]] || {
  printf 'Release image manifest parser returned an unexpected value contract.\n' >&2
  exit 1
}
AC_ADMIN_IMAGE="${release_image_values[0]}"
AC_ADMIN_REGISTRY_DIGEST="${release_image_values[1]}"
AC_ADMIN_TRANSPORT_DIGEST="${release_image_values[2]}"
AC_API_IMAGE="${release_image_values[3]}"
AC_API_REGISTRY_DIGEST="${release_image_values[4]}"
AC_API_TRANSPORT_DIGEST="${release_image_values[5]}"
AC_LEARNER_IMAGE="${release_image_values[6]}"
AC_LEARNER_REGISTRY_DIGEST="${release_image_values[7]}"
AC_LEARNER_TRANSPORT_DIGEST="${release_image_values[8]}"
AC_MIGRATION_HEAD="${release_image_values[9]}"
AC_RELEASE_ID="${release_image_values[10]}"
unset release_image_values
[[ "$AC_RELEASE_ID" == "$release_id" ]]
for image_id in "$AC_API_IMAGE" "$AC_LEARNER_IMAGE" "$AC_ADMIN_IMAGE"; do
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    printf 'Application deployment requires exact local OCI manifest IDs.\n' >&2
    exit 1
  }
done
for transport_digest in \
  "$AC_API_TRANSPORT_DIGEST" \
  "$AC_LEARNER_TRANSPORT_DIGEST" \
  "$AC_ADMIN_TRANSPORT_DIGEST"; do
  [[ "$transport_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    printf 'Application deployment requires exact OCI transport manifest digests.\n' >&2
    exit 1
  }
done

expected_bundle_files=(
  SHA256SUMS
  application-images.tar.gz
  release-images.env
)
release_images_file="$image_bundle_dir/release-images.env"

if [[ -e "$artifact_dir" || -L "$artifact_dir" ]]; then
  [[ -d "$artifact_dir" && ! -L "$artifact_dir" ]] || {
    printf 'Existing release artifact path is not a directory.\n' >&2
    exit 1
  }
  python3 "$script_dir/prepare-release-inputs.py" verify-bundle \
    "$artifact_dir" "$release_id" > /dev/null
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
  python3 "$script_dir/prepare-release-inputs.py" verify-bundle \
    "$artifact_stage" "$release_id" > /dev/null
  find "$artifact_stage" -type d -exec chmod 0750 {} +
  find "$artifact_stage" -type f -exec chmod 0640 {} +
  chown -R root:acops "$artifact_stage"
  mv --no-target-directory "$artifact_stage" "$artifact_dir"
  artifact_stage=''
fi

if [[ -e "$release_dir" || -L "$release_dir" ]]; then
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
  mv --no-target-directory "$stage_dir" "$release_dir"
  stage_dir=''
fi

secret_environment="$target_environment"
[[ "$target_environment" == production ]] && secret_environment=prod

with_release_secrets() {
  env \
    -u AC_GOOGLE_OAUTH_CLIENT_ID \
    -u AC_GOOGLE_OAUTH_CLIENT_SECRET \
    AC_INFISICAL_ENVIRONMENT="$secret_environment" \
    AC_INFISICAL_PATH="$secret_path" \
    /usr/local/sbin/ac-infisical-run -- "$@"
}

# Infisical may supply a syntactically present but whitespace-only value that
# Compose's `${VAR:?}` interpolation accepts. Reject that state before loading
# images, creating environment state, or issuing any Docker Compose command.
with_release_secrets \
  python3 "$release_dir/scripts/validate-google-oauth-secrets.py"

gzip --decompress --stdout "$image_bundle_dir/application-images.tar.gz" | docker load >/dev/null
for image_id in "$AC_API_IMAGE" "$AC_LEARNER_IMAGE" "$AC_ADMIN_IMAGE"; do
  [[ "$(docker image inspect --format '{{.Id}}' "$image_id")" == "$image_id" ]] || {
    printf 'Loaded image identity verification failed: %s\n' "$image_id" >&2
    exit 1
  }
done

api_release_marker_file="$input_stage/api-release-marker"
expected_api_release_marker_file="$input_stage/expected-api-release-marker"
docker run --rm --pull never --network none --read-only \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --entrypoint /bin/sh "$AC_API_IMAGE" -euc 'cat /app/.ac-release-id' \
  > "$api_release_marker_file"
printf '%s\n' "$release_id" > "$expected_api_release_marker_file"
if ! cmp --silent "$api_release_marker_file" "$expected_api_release_marker_file"; then
  printf 'Loaded API image release marker does not match the release ID.\n' >&2
  exit 1
fi
rm -- "$api_release_marker_file" "$expected_api_release_marker_file"

api_migration_heads_file="$input_stage/api-migration-heads"
docker run --rm --pull never --network none --read-only \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --entrypoint alembic "$AC_API_IMAGE" heads > "$api_migration_heads_file"
mapfile -t loaded_api_migration_heads < "$api_migration_heads_file"
rm -- "$api_migration_heads_file"
if [[ "${#loaded_api_migration_heads[@]}" -ne 1 \
  || ! "${loaded_api_migration_heads[0]}" =~ ^([0-9]{8}_[0-9]{4})[[:space:]]+\(head\)$ \
  || "${BASH_REMATCH[1]}" != "$AC_MIGRATION_HEAD" ]]; then
  printf 'Loaded API image migration head does not match the reviewed bundle.\n' >&2
  exit 1
fi
unset loaded_api_migration_heads

profile_file="$release_dir/environments/$target_environment.env"
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
  with_release_secrets \
    env \
        -u AC_COMPOSE_PROJECT \
        -u AC_ENVIRONMENT \
        -u AC_STATE_ROOT \
        -u AC_PUBLIC_APP_URL \
        -u AC_ADMIN_APP_URL \
        -u AC_API_URL \
        -u AC_API_HOST \
        -u AC_INTERNAL_API_HOST \
        -u AC_TRUSTED_PROXY_ADDRESSES \
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
current_switch_armed=0
current_tmp=''
evidence_tmp=''

set_database_writer_access() {
  local access_mode="$1"
  # shellcheck disable=SC2016  # PostgreSQL container variables expand inside `sh -euc`.
  compose_for "$release_dir" exec -T postgres sh -euc '
    export PGPASSWORD="$POSTGRES_PASSWORD"
    [ "$POSTGRES_DB" = ac_platform ] || {
      printf "Unexpected application database identity.\n" >&2
      exit 1
    }
    case "$1" in
      fence)
        psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
REVOKE CONNECT ON DATABASE ac_platform FROM PUBLIC, ac_runtime, ac_migrator;
GRANT CONNECT ON DATABASE ac_platform TO ac_owner, ac_backup;
SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
 WHERE datname = '\''ac_platform'\''
   AND usename IN ('\''ac_runtime'\'', '\''ac_migrator'\'')
   AND pid <> pg_backend_pid();
SQL
        remaining="$(
          psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres -Atqc \
            "SELECT count(*) FROM pg_stat_activity WHERE datname = '\''ac_platform'\'' AND usename IN ('\''ac_runtime'\'', '\''ac_migrator'\'')"
        )"
        [ "$remaining" = 0 ] || {
          printf "Application database writers did not quiesce.\n" >&2
          exit 1
        }
        ;;
      migrator)
        psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
          -c "GRANT CONNECT ON DATABASE ac_platform TO ac_migrator"
        ;;
      runtime)
        psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
          -c "GRANT CONNECT ON DATABASE ac_platform TO ac_migrator, ac_runtime"
        ;;
      *)
        printf "Unsupported database access mode.\n" >&2
        exit 1
        ;;
    esac
  ' sh "$access_mode"
}

restore_current_link() {
  local rollback_tmp current_target
  [[ "$current_switch_armed" == 1 ]] || return 0
  if [[ -n "$previous_release" ]]; then
    rollback_tmp="$application_root/.rollback-${target_environment}-${release_id}.$$"
    [[ ! -e "$rollback_tmp" && ! -L "$rollback_tmp" ]] || return 1
    if ! ln -s "$previous_release" "$rollback_tmp"; then
      return 1
    fi
    if ! mv --no-target-directory --force "$rollback_tmp" "$current_link"; then
      rm -f -- "$rollback_tmp"
      return 1
    fi
    if [[ "$(readlink -f "$current_link")" != "$previous_release" ]]; then
      return 1
    fi
  else
    if [[ -L "$current_link" ]]; then
      if ! current_target="$(readlink -f "$current_link")"; then
        return 1
      fi
      [[ "$current_target" == "$release_dir" ]] || return 1
      rm -- "$current_link" || return 1
    elif [[ -e "$current_link" ]]; then
      return 1
    fi
    [[ ! -e "$current_link" && ! -L "$current_link" ]] || return 1
  fi
  current_switch_armed=0
}

rollback_release() {
  local rollback_failed=0 rollback_fenced=0
  printf 'ROLLBACK  Restoring %s after failed release %s.\n' "$target_environment" "$release_id" >&2
  if [[ -n "$current_tmp" && -L "$current_tmp" ]]; then
    rm -- "$current_tmp" || rollback_failed=1
  fi
  if [[ -n "$evidence_tmp" && -f "$evidence_tmp" ]]; then
    rm -- "$evidence_tmp" || rollback_failed=1
  fi
  compose_for "$release_dir" stop --timeout 30 api worker learner-web admin-web \
    >/dev/null 2>&1 || rollback_failed=1
  if set_database_writer_access fence; then
    rollback_fenced=1
  else
    rollback_failed=1
  fi
  if [[ "$backup_ready" == 1 && "$rollback_fenced" == 1 ]]; then
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
  if [[ "$rollback_fenced" == 1 && "$rollback_failed" == 0 ]]; then
    if set_database_writer_access runtime; then
      : # The database is reopened only after its restore completed successfully.
    else
      rollback_failed=1
    fi
  fi
  if [[ "$rollback_failed" == 0 ]]; then
    restore_current_link || rollback_failed=1
  fi
  if [[ "$rollback_failed" == 0 ]]; then
    if [[ -n "$previous_release" ]]; then
      compose_for "$previous_release" up --detach --remove-orphans --wait --wait-timeout 180 \
        || rollback_failed=1
    else
      compose_for "$release_dir" down --remove-orphans --timeout 30 || rollback_failed=1
    fi
  fi
  [[ "$rollback_failed" == 0 ]] || {
    printf 'FAIL  Automatic application rollback was incomplete.\n' >&2
    return 1
  }
  printf 'ROLLBACK  Database and previous application release restored.\n' >&2
}

finish() {
  local status=$?
  # Once finalization starts, allow the rollback to finish unless the host or
  # process is forcibly killed. A second catchable signal must not recurse.
  trap '' HUP INT TERM
  trap - EXIT
  if [[ "$status" -ne 0 && "$mutation_started" == 1 && "$release_committed" == 0 ]]; then
    rollback_release || status=1
  fi
  if ! cleanup_stages; then
    [[ "$status" -ne 0 ]] || status=1
  fi
  exit "$status"
}
trap finish EXIT

mutation_started=1
writer_release="$release_dir"
if [[ -n "$previous_release" ]]; then
  writer_release="$previous_release"
fi
compose_for "$writer_release" stop --timeout 30 api worker
compose_for "$release_dir" up --detach --wait --wait-timeout 180 postgres
set_database_writer_access fence
umask 077
# shellcheck disable=SC2016  # Backup credentials and database name expand only in the container.
compose_for "$release_dir" exec -T postgres sh -euc '
  export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"
  pg_dump -h 127.0.0.1 -U ac_backup -d "$POSTGRES_DB" --format=custom --create
' > "$backup_file"
compose_for "$release_dir" exec -T postgres pg_restore --list < "$backup_file" >/dev/null
backup_ready=1

set_database_writer_access migrator
compose_for "$release_dir" --profile release run --rm migrate
set_database_writer_access runtime
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
current_switch_armed=1
mv --no-target-directory --force "$current_tmp" "$current_link"
current_tmp=''
[[ "$(readlink -f "$current_link")" == "$release_dir" ]]

evidence_root="$application_root/deployments/$target_environment"
install -d -m 0750 -o root -g acops "$evidence_root"
evidence_file="$evidence_root/$(date -u +%Y%m%dT%H%M%SZ)-${release_id}.env"
evidence_tmp="$(mktemp "$evidence_root/.deployment-${release_id}.XXXXXX")"
{
  printf 'AC_ENVIRONMENT=%s\n' "$target_environment"
  printf 'AC_RELEASE_ID=%s\n' "$release_id"
  printf 'AC_PREVIOUS_RELEASE=%s\n' "${previous_release##*/}"
  printf 'AC_PRE_MIGRATION_BACKUP=%s\n' "$backup_file"
  printf 'AC_API_IMAGE=%s\n' "$AC_API_IMAGE"
  printf 'AC_API_REGISTRY_DIGEST=%s\n' "$AC_API_REGISTRY_DIGEST"
  printf 'AC_API_TRANSPORT_DIGEST=%s\n' "$AC_API_TRANSPORT_DIGEST"
  printf 'AC_LEARNER_IMAGE=%s\n' "$AC_LEARNER_IMAGE"
  printf 'AC_LEARNER_REGISTRY_DIGEST=%s\n' "$AC_LEARNER_REGISTRY_DIGEST"
  printf 'AC_LEARNER_TRANSPORT_DIGEST=%s\n' "$AC_LEARNER_TRANSPORT_DIGEST"
  printf 'AC_MIGRATION_HEAD=%s\n' "$AC_MIGRATION_HEAD"
  printf 'AC_ADMIN_IMAGE=%s\n' "$AC_ADMIN_IMAGE"
  printf 'AC_ADMIN_REGISTRY_DIGEST=%s\n' "$AC_ADMIN_REGISTRY_DIGEST"
  printf 'AC_ADMIN_TRANSPORT_DIGEST=%s\n' "$AC_ADMIN_TRANSPORT_DIGEST"
} > "$evidence_tmp"
chmod 0640 "$evidence_tmp"
chown root:acops "$evidence_tmp"
mv --no-target-directory "$evidence_tmp" "$evidence_file"
evidence_tmp=''
release_committed=1

printf 'PASS  %s now runs exact release %s with held external side effects.\n' \
  "$target_environment" "$release_id"
