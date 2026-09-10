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
edge_routes_root="$application_root/edge-routes"
edge_route_releases_root="$application_root/edge-route-releases"
edge_route_projection="$edge_route_releases_root/$release_id"
edge_route_link="$edge_routes_root/$target_environment.caddy"
foundation_current_link=/srv/authority-closers/current
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
[[ "${#release_image_values[@]}" -eq 14 ]] || {
  printf 'Release image manifest parser returned an unexpected value contract.\n' >&2
  exit 1
}
AC_ADMIN_IMAGE="${release_image_values[0]}"
AC_ADMIN_REGISTRY_DIGEST="${release_image_values[1]}"
AC_ADMIN_TRANSPORT_DIGEST="${release_image_values[2]}"
AC_API_IMAGE="${release_image_values[3]}"
AC_API_REGISTRY_DIGEST="${release_image_values[4]}"
AC_API_TRANSPORT_DIGEST="${release_image_values[5]}"
AC_COACH_IMAGE="${release_image_values[6]}"
AC_COACH_REGISTRY_DIGEST="${release_image_values[7]}"
AC_COACH_TRANSPORT_DIGEST="${release_image_values[8]}"
AC_LEARNER_IMAGE="${release_image_values[9]}"
AC_LEARNER_REGISTRY_DIGEST="${release_image_values[10]}"
AC_LEARNER_TRANSPORT_DIGEST="${release_image_values[11]}"
AC_MIGRATION_HEAD="${release_image_values[12]}"
AC_RELEASE_ID="${release_image_values[13]}"
unset release_image_values
[[ "$AC_RELEASE_ID" == "$release_id" ]]
for image_id in "$AC_API_IMAGE" "$AC_LEARNER_IMAGE" "$AC_ADMIN_IMAGE" "$AC_COACH_IMAGE"; do
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    printf 'Application deployment requires exact local OCI manifest IDs.\n' >&2
    exit 1
  }
done
for transport_digest in \
  "$AC_API_TRANSPORT_DIGEST" \
  "$AC_LEARNER_TRANSPORT_DIGEST" \
  "$AC_ADMIN_TRANSPORT_DIGEST" \
  "$AC_COACH_TRANSPORT_DIGEST"; do
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
  find "$stage_dir/edge-routes" -type f -exec chmod 0644 {} +
  find "$stage_dir/scripts" -type f -exec chmod 0750 {} +
  chown -R root:acops "$stage_dir"
  mv --no-target-directory "$stage_dir" "$release_dir"
  stage_dir=''
fi

secret_environment="$target_environment"
[[ "$target_environment" == production ]] && secret_environment=prod

profile_file="$release_dir/environments/$target_environment.env"
declare -a profile_required_keys=()
declare -A profile_values=()
declare -A profile_allowed_keys=()

initialize_release_profile_contract() {
  local profile_key
  profile_required_keys=(
    AC_COMPOSE_PROJECT
    AC_ENVIRONMENT
    AC_STATE_ROOT
    AC_PUBLIC_APP_URL
    AC_ADMIN_APP_URL
    AC_COACH_APP_URL
    AC_API_URL
    AC_API_HOST
    AC_INTERNAL_API_HOST
    AC_TRUSTED_PROXY_ADDRESSES
    AC_EDGE_API_ALIAS
    AC_EDGE_LEARNER_ALIAS
    AC_EDGE_ADMIN_ALIAS
    AC_EDGE_COACH_ALIAS
    AC_EXTERNAL_SIDE_EFFECTS_HOLD
    AC_EMAIL_PROVIDER
    AC_PRACTICE_PILOT_ENABLED
  )
  if [[ "$target_environment" == staging ]]; then
    profile_required_keys+=(AC_LEARNER_CONSENT_VERSION)
  fi
  profile_allowed_keys=()
  for profile_key in "${profile_required_keys[@]}"; do
    profile_allowed_keys["$profile_key"]=1
  done
}

initialize_release_profile_contract

load_release_profile() {
  local line key value
  [[ -f "$profile_file" && ! -L "$profile_file" && -r "$profile_file" ]] || {
    printf 'Released environment profile is not a readable regular file.\n' >&2
    return 1
  }
  if LC_ALL=C grep -U -q $'\r' "$profile_file"; then
    printf 'Released environment profile must use canonical LF line endings.\n' >&2
    return 1
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == *=* ]] || {
      printf 'Released environment profile has a malformed assignment.\n' >&2
      return 1
    }
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || {
      printf 'Released environment profile has a malformed key.\n' >&2
      return 1
    }
    [[ -n "${profile_allowed_keys[$key]+present}" ]] || {
      printf 'Released environment profile has an unexpected key.\n' >&2
      return 1
    }
    [[ -z "${profile_values[$key]+present}" ]] || {
      printf 'Released environment profile has a duplicate assignment.\n' >&2
      return 1
    }
    [[ -n "$value" && "$value" =~ ^[A-Za-z0-9_./:@+%=-]+$ ]] || {
      printf 'Released environment profile has an empty or unsafe assignment.\n' >&2
      return 1
    }
    profile_values["$key"]="$value"
  done < "$profile_file"
}

profile_value() {
  local key="$1"
  [[ -n "${profile_values[$key]+present}" ]] || {
    printf 'Released environment profile is missing %s.\n' "$key" >&2
    return 1
  }
  printf '%s' "${profile_values[$key]}"
}

validate_release_profile() {
  local expected_profile_assignment expected_profile_key expected_profile_value actual_profile_value
  load_release_profile

  local -a expected_profile_assignments=(
    "AC_COMPOSE_PROJECT=ac-application-$target_environment"
    "AC_ENVIRONMENT=$target_environment"
    "AC_STATE_ROOT=/srv/authority-closers/state/application/$target_environment"
  )
  case "$target_environment" in
    staging)
      expected_profile_assignments+=(
        "AC_PUBLIC_APP_URL=https://learner-staging.authorityclosers.com"
        "AC_ADMIN_APP_URL=https://admin-staging.authorityclosers.com"
        "AC_COACH_APP_URL=https://coach-staging.authorityclosers.com"
        "AC_API_URL=https://api-staging.authorityclosers.com"
        "AC_API_HOST=api-staging.authorityclosers.com"
        "AC_INTERNAL_API_HOST=api.staging.ac.internal.invalid"
        "AC_TRUSTED_PROXY_ADDRESSES=172.18.0.2"
        "AC_EDGE_API_ALIAS=ac-staging-api"
        "AC_EDGE_LEARNER_ALIAS=ac-staging-learner"
        "AC_EDGE_ADMIN_ALIAS=ac-staging-admin"
        "AC_EDGE_COACH_ALIAS=ac-staging-coach"
        "AC_EXTERNAL_SIDE_EFFECTS_HOLD=false"
        "AC_EMAIL_PROVIDER=resend"
        "AC_LEARNER_CONSENT_VERSION=staging-test-document-v1"
        "AC_PRACTICE_PILOT_ENABLED=true"
      )
      ;;
    production)
      expected_profile_assignments+=(
        "AC_PUBLIC_APP_URL=https://learner.authorityclosers.com"
        "AC_ADMIN_APP_URL=https://admin.authorityclosers.com"
        "AC_COACH_APP_URL=https://coach.authorityclosers.com"
        "AC_API_URL=https://api.authorityclosers.com"
        "AC_API_HOST=api.authorityclosers.com"
        "AC_INTERNAL_API_HOST=api.production.ac.internal.invalid"
        "AC_TRUSTED_PROXY_ADDRESSES=172.18.0.2"
        "AC_EDGE_API_ALIAS=ac-production-api"
        "AC_EDGE_LEARNER_ALIAS=ac-production-learner"
        "AC_EDGE_ADMIN_ALIAS=ac-production-admin"
        "AC_EDGE_COACH_ALIAS=ac-production-coach"
        "AC_EXTERNAL_SIDE_EFFECTS_HOLD=true"
        "AC_EMAIL_PROVIDER=fake"
        "AC_PRACTICE_PILOT_ENABLED=false"
      )
      ;;
  esac
  for expected_profile_assignment in "${expected_profile_assignments[@]}"; do
    expected_profile_key="${expected_profile_assignment%%=*}"
    expected_profile_value="${expected_profile_assignment#*=}"
    actual_profile_value="$(profile_value "$expected_profile_key")"
    [[ "$actual_profile_value" == "$expected_profile_value" ]] || {
      printf 'Released environment profile has an unexpected value for %s.\n' \
        "$expected_profile_key" >&2
      return 1
    }
  done

  compose_project="$(profile_value AC_COMPOSE_PROJECT)"
  state_root="$(profile_value AC_STATE_ROOT)"

  external_side_effects_hold="$(profile_value AC_EXTERNAL_SIDE_EFFECTS_HOLD)"
  case "$external_side_effects_hold" in
    true) external_side_effects_status='held' ;;
    false) external_side_effects_status='released' ;;
    *)
      printf 'Released environment profile has an invalid external-effects hold policy.\n' >&2
      return 1
      ;;
  esac

  email_provider="$(profile_value AC_EMAIL_PROVIDER)"
  case "$email_provider" in
    fake|resend) ;;
    *)
      printf 'Released environment profile has an unsupported email provider.\n' >&2
      return 1
      ;;
  esac

  learner_host="$(profile_value AC_PUBLIC_APP_URL)"
  learner_host="${learner_host#https://}"
  admin_host="$(profile_value AC_ADMIN_APP_URL)"
  admin_host="${admin_host#https://}"
  coach_host="$(profile_value AC_COACH_APP_URL)"
  coach_host="${coach_host#https://}"
  api_host="$(profile_value AC_API_HOST)"
}

validate_release_profile

with_release_secrets() {
  env \
    -u AC_GOOGLE_OAUTH_CLIENT_ID \
    -u AC_GOOGLE_OAUTH_CLIENT_SECRET \
    -u AC_EMAIL_CHALLENGE_SECRET \
    -u AC_PUBLIC_LEARNER_TENANT_ID \
    -u AC_OPERATIONS_TENANT_ID \
    -u AC_PRACTICE_PILOT_TENANT_ID \
    AC_INFISICAL_ENVIRONMENT="$secret_environment" \
    AC_INFISICAL_PATH="$secret_path" \
    /usr/local/sbin/ac-infisical-run -- "$@"
}

with_practice_pilot_scope() {
  # AC_PRACTICE_PILOT_TENANT_ID is derived only after the managed environment
  # has supplied the canonical public learner reference. A host or managed
  # value under the pilot-specific name can therefore never select scope.
  with_release_secrets \
    sh -euc '
      AC_PRACTICE_PILOT_TENANT_ID="${AC_PUBLIC_LEARNER_TENANT_ID:-}"
      export AC_PRACTICE_PILOT_TENANT_ID
      exec "$@"
    ' sh "$@"
}

validate_practice_pilot_references() {
  # The release profile owns whether the pilot is enabled. Its tenant scope is
  # derived from the separately managed, non-secret public learner reference.
  with_practice_pilot_scope \
    env AC_RELEASE_PRACTICE_PILOT_ENABLED="$(profile_value AC_PRACTICE_PILOT_ENABLED)" \
    python3 -c '
import os
from uuid import UUID

enabled = os.environ["AC_RELEASE_PRACTICE_PILOT_ENABLED"] == "true"
if enabled:
    names = (
        "AC_PRACTICE_PILOT_TENANT_ID",
        "AC_PUBLIC_LEARNER_TENANT_ID",
        "AC_OPERATIONS_TENANT_ID",
    )
    parsed = {}
    for name in names:
        raw = os.environ.get(name, "")
        if not raw or raw != raw.strip():
            raise SystemExit("Practice pilot requires exact managed tenant references.")
        try:
            parsed[name] = UUID(raw)
        except ValueError:
            raise SystemExit("Practice pilot requires exact managed tenant references.") from None
    if (
        parsed["AC_PRACTICE_PILOT_TENANT_ID"]
        != parsed["AC_PUBLIC_LEARNER_TENANT_ID"]
        or parsed["AC_PRACTICE_PILOT_TENANT_ID"]
        == parsed["AC_OPERATIONS_TENANT_ID"]
    ):
        raise SystemExit(
            "Practice pilot tenant must match public learner and differ from operations."
        )
'
}

# Infisical may supply a syntactically present but whitespace-only value that
# Compose's `${VAR:?}` interpolation accepts. Reject that state before loading
# images, creating environment state, or issuing any Docker Compose command.
with_release_secrets \
  python3 "$release_dir/scripts/validate-google-oauth-secrets.py"
validate_practice_pilot_references

gzip --decompress --stdout "$image_bundle_dir/application-images.tar.gz" | docker load >/dev/null
for image_id in "$AC_API_IMAGE" "$AC_LEARNER_IMAGE" "$AC_ADMIN_IMAGE" "$AC_COACH_IMAGE"; do
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

install -d -m 0750 -o root -g acops "$state_root"
install -d -m 0700 -o 999 -g 999 "$state_root/postgres"

python3 "$release_dir/scripts/staging-public-films.py" \
  preflight "$release_dir" "$target_environment"
python3 "$release_dir/scripts/public-films.py" \
  preflight "$release_dir" "$target_environment"

compose_for() {
  local target_release="$1"
  shift
  local fixture_override=''
  local public_film_override=''
  local -a fixture_compose_files=()
  # Resolve the target release's policy on every call, including rollback.
  # Old releases without a policy remain off; production never merges it.
  if [[ "$target_environment" == staging && (
    -e "$target_release/capabilities/staging-public-films.json" ||
    -L "$target_release/capabilities/staging-public-films.json"
  ) ]]; then
    fixture_override="$(python3 "$release_dir/scripts/staging-public-films.py" \
      compose-file "$target_release" "$target_environment")" || return 1
    if [[ -n "$fixture_override" ]]; then
      fixture_compose_files=(--file "$fixture_override")
    fi
  fi
  # Select the rollback target's own immutable policy, never the current flag.
  if [[ -e "$target_release/capabilities/public-films.json" ||
        -L "$target_release/capabilities/public-films.json" ]]; then
    public_film_override="$(python3 "$release_dir/scripts/public-films.py" \
      compose-file "$target_release" "$target_environment")" || return 1
    if [[ -n "$public_film_override" ]]; then
      if [[ -n "$fixture_override" ]]; then
        printf 'Legacy staging and public-film delivery cannot be enabled together.\n' >&2
        return 1
      fi
      fixture_compose_files=(--file "$public_film_override")
    fi
  fi
  with_practice_pilot_scope \
    env \
        -u COMPOSE_PROJECT_NAME \
        -u COMPOSE_FILE \
        -u COMPOSE_PROFILES \
        -u COMPOSE_PATH_SEPARATOR \
        -u COMPOSE_ENV_FILES \
        -u COMPOSE_DISABLE_ENV_FILE \
        -u AC_COMPOSE_PROJECT \
        -u AC_ENVIRONMENT \
        -u AC_STATE_ROOT \
        -u AC_PUBLIC_APP_URL \
        -u AC_ADMIN_APP_URL \
        -u AC_COACH_APP_URL \
        -u AC_API_URL \
        -u AC_API_HOST \
        -u AC_INTERNAL_API_HOST \
        -u AC_TRUSTED_PROXY_ADDRESSES \
        -u AC_EDGE_API_ALIAS \
        -u AC_EDGE_LEARNER_ALIAS \
        -u AC_EDGE_ADMIN_ALIAS \
        -u AC_EDGE_COACH_ALIAS \
        -u AC_EXTERNAL_SIDE_EFFECTS_HOLD \
        -u AC_EMAIL_PROVIDER \
        -u AC_PRACTICE_PILOT_ENABLED \
        -u AC_LEARNER_CONSENT_VERSION \
        -u AC_LOG_LEVEL \
        -u AC_OTEL_EXPORTER_OTLP_ENDPOINT \
        -u AC_POSTGRES_IMAGE \
        -u AC_RELEASE_ID \
        -u AC_API_IMAGE \
        -u AC_LEARNER_IMAGE \
        -u AC_ADMIN_IMAGE \
        -u AC_COACH_IMAGE \
        -u AC_MEDIA_PROVIDER_ENABLED \
        -u AC_MEDIA_STRESS_FIXTURES_ENABLED \
        -u AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT \
        -u AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED \
        -u AC_MEDIA_PUBLIC_FILMS_DELIVERY_ENABLED \
        -u AC_MEDIA_PUBLIC_FILMS_ROOT \
    docker compose \
      --project-name "$compose_project" \
      --env-file "$target_release/environments/$target_environment.env" \
      --env-file "$target_release/release-images.env" \
      --file "$target_release/compose.yaml" \
      "${fixture_compose_files[@]}" \
      "$@"
}

compose_for "$release_dir" config --quiet
released_edge_route_source="$release_dir/edge-routes/$target_environment.caddy"
released_edge_hold_source="$release_dir/edge-routes/$target_environment-hold.caddy"
for edge_source in "$released_edge_route_source" "$released_edge_hold_source"; do
  [[ -f "$edge_source" && ! -L "$edge_source" && -r "$edge_source" ]] || {
    printf 'Released edge-route input is not a readable regular file.\n' >&2
    exit 1
  }
done
if [[ -e "$edge_route_releases_root" || -L "$edge_route_releases_root" ]]; then
  [[ -d "$edge_route_releases_root" && ! -L "$edge_route_releases_root" ]] || {
    printf 'Application edge-route projection root is not a real directory.\n' >&2
    exit 1
  }
fi
install -d -m 0755 -o root -g root "$edge_route_releases_root"
# A setgid application parent makes GNU install inherit the setgid bit. Keep
# this projection boundary an ordinary root-owned 755 directory before
# validating or adding the immutable route projection.
chmod 0755 "$edge_route_releases_root"
chmod a-s "$edge_route_releases_root"
if [[ ! -e "$edge_route_projection" && ! -L "$edge_route_projection" ]]; then
  edge_projection_stage="$(mktemp -d "$edge_route_releases_root/.${release_id}.XXXXXX")"
  for projection_environment in production staging; do
    install -m 0444 -o root -g root \
      "$release_dir/edge-routes/$projection_environment.caddy" \
      "$edge_projection_stage/$projection_environment.caddy"
    install -m 0444 -o root -g root \
      "$release_dir/edge-routes/$projection_environment-hold.caddy" \
      "$edge_projection_stage/$projection_environment-hold.caddy"
  done
  chmod 0755 "$edge_projection_stage"
  chown root:root "$edge_projection_stage"
  mv --no-target-directory --no-clobber "$edge_projection_stage" "$edge_route_projection"
elif [[ ! -d "$edge_route_projection" || -L "$edge_route_projection" ]]; then
  printf 'Application edge-route projection is not a real directory.\n' >&2
  exit 1
fi
[[ "$(stat -c '%U:%G %a' "$edge_route_releases_root")" == 'root:root 755' ]]
[[ "$(stat -c '%U:%G %a' "$edge_route_projection")" == 'root:root 755' ]]
mapfile -t projected_edge_files < <(
  find "$edge_route_projection" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort
)
[[ "${projected_edge_files[*]}" == 'production-hold.caddy production.caddy staging-hold.caddy staging.caddy' ]] || {
  printf 'Application edge-route projection has an unexpected file set.\n' >&2
  exit 1
}
for projection_environment in production staging; do
  for projection_name in "$projection_environment.caddy" "$projection_environment-hold.caddy"; do
    projection_source="$release_dir/edge-routes/$projection_name"
    projection_target="$edge_route_projection/$projection_name"
    [[ -f "$projection_target" && ! -L "$projection_target" ]] || exit 1
    [[ "$(stat -c '%U:%G %a' "$projection_target")" == 'root:root 444' ]] || exit 1
    cmp --silent "$projection_source" "$projection_target" || {
      printf 'Application edge-route projection differs from its immutable release.\n' >&2
      exit 1
    }
  done
done
edge_route_source="$edge_route_projection/$target_environment.caddy"
edge_hold_source="$edge_route_projection/$target_environment-hold.caddy"
[[ -d "$edge_routes_root" && ! -L "$edge_routes_root" ]] || {
  printf 'Application edge-route selector root is not a real directory.\n' >&2
  exit 1
}
[[ "$(stat -c '%U:%G %a' "$edge_routes_root")" == 'root:root 755' ]] || {
  printf 'Application edge-route selector root has unexpected ownership or mode.\n' >&2
  exit 1
}

validate_released_edge_route_target() {
  local selector_environment="$1" selector="$2" target projection_release_id
  local owner_release expected_source
  [[ -L "$selector" ]] || {
    printf 'Application %s edge-route selector is not a symbolic link.\n' \
      "$selector_environment" >&2
    return 1
  }
  target="$(readlink -f "$selector")"
  [[ -f "$target" && ! -L "$target" ]] || {
    printf 'Application %s edge-route selector target is not a regular file.\n' \
      "$selector_environment" >&2
    return 1
  }
  case "$target" in
    "$edge_route_releases_root"/foundation-[0-9a-f]*/"$selector_environment".caddy)
      projection_release_id="$(basename "$(dirname "$target")")"
      [[ "$projection_release_id" =~ ^foundation-[0-9a-f]{40}$ ]] || return 1
      owner_release="/srv/authority-closers/releases/$projection_release_id"
      expected_source="$owner_release/compose/foundation/application-routes/$selector_environment.caddy"
      ;;
    "$edge_route_releases_root"/[0-9a-f]*/"$selector_environment".caddy|\
    "$edge_route_releases_root"/[0-9a-f]*/"$selector_environment"-hold.caddy)
      projection_release_id="$(basename "$(dirname "$target")")"
      [[ "$projection_release_id" =~ ^[0-9a-f]{40}$ ]] || return 1
      owner_release="$releases_root/$projection_release_id"
      expected_source="$owner_release/edge-routes/$(basename "$target")"
      ;;
    *)
      printf 'Application %s edge-route selector resolves outside immutable releases.\n' \
        "$selector_environment" >&2
      return 1
      ;;
  esac
  if [[ "$projection_release_id" == foundation-* ]]; then
    [[ -f "$owner_release/RELEASE-ID" && \
       "$(<"$owner_release/RELEASE-ID")" == "$projection_release_id" ]] || return 1
    [[ -f "$owner_release/RELEASE-COMMIT" && \
       "$(<"$owner_release/RELEASE-COMMIT")" == "${projection_release_id#foundation-}" ]] || return 1
  else
    [[ -f "$owner_release/RELEASE-COMMIT" && \
       "$(<"$owner_release/RELEASE-COMMIT")" == "$projection_release_id" ]] || return 1
  fi
  [[ -f "$owner_release/RELEASE-FILES.sha256" && ! -L "$owner_release/RELEASE-FILES.sha256" ]] || {
    printf 'Edge-route owner has no immutable release checksum manifest.\n' >&2
    return 1
  }
  (cd "$owner_release" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null) || {
    printf 'Edge-route owner failed immutable release verification.\n' >&2
    return 1
  }
  [[ -f "$expected_source" && ! -L "$expected_source" ]] || return 1
  [[ "$(stat -c '%U:%G %a' "$target")" == 'root:root 444' ]] || return 1
  cmp --silent "$expected_source" "$target" || {
    printf 'Edge-route projection differs from its checksum-verified owner.\n' >&2
    return 1
  }
  printf '%s\n' "$target"
}

previous_edge_route_target=''
for selector_environment in production staging; do
  selector_target="$(validate_released_edge_route_target \
    "$selector_environment" "$edge_routes_root/$selector_environment.caddy")"
  if [[ "$selector_environment" == "$target_environment" ]]; then
    previous_edge_route_target="$selector_target"
  fi
done
[[ -n "$previous_edge_route_target" ]]

[[ -L "$foundation_current_link" ]] || {
  printf 'Current foundation release link is unavailable.\n' >&2
  exit 1
}
foundation_release="$(readlink -f "$foundation_current_link")"
[[ "$foundation_release" == /srv/authority-closers/releases/foundation-[0-9a-f]* ]] || {
  printf 'Current foundation release does not resolve inside its immutable root.\n' >&2
  exit 1
}
foundation_release_id="${foundation_release##*/}"
[[ "$foundation_release_id" =~ ^foundation-[0-9a-f]{40}$ ]] || {
  printf 'Current foundation release identity is malformed.\n' >&2
  exit 1
}
[[ -f "$foundation_release/RELEASE-ID" && \
   "$(<"$foundation_release/RELEASE-ID")" == "$foundation_release_id" ]]
[[ -f "$foundation_release/RELEASE-COMMIT" && \
   "$(<"$foundation_release/RELEASE-COMMIT")" == "${foundation_release_id#foundation-}" ]]
(cd "$foundation_release" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
foundation_caddyfile="$foundation_release/compose/foundation/Caddyfile"
foundation_compose_file="$foundation_release/compose/foundation/compose.yaml"
foundation_image_env="$foundation_release/config/release/foundation-images.env"
grep -Fxq $'\timport /etc/caddy/application-routes/production.caddy' "$foundation_caddyfile"
grep -Fxq $'\timport /etc/caddy/application-routes/staging.caddy' "$foundation_caddyfile"
grep -Fq '/srv/authority-closers/application/edge-routes:/etc/caddy/application-routes:ro' \
  "$foundation_compose_file"
grep -Fq '/srv/authority-closers/application/edge-route-releases:/srv/authority-closers/application/edge-route-releases:ro' \
  "$foundation_compose_file"
docker compose --env-file "$foundation_image_env" -f "$foundation_compose_file" config --quiet
edge_mount="$({
  docker inspect ac-edge-router --format \
    '{{range .Mounts}}{{if eq .Destination "/etc/caddy/application-routes"}}{{println .Source "|" .RW}}{{end}}{{end}}'
} | tr -d '\r' | sed '/^$/d')"
[[ "$edge_mount" == "$edge_routes_root | false" ]] || {
  printf 'Running edge router does not use the reviewed read-only route selector mount.\n' >&2
  exit 1
}
route_projection_mount="$({
  docker inspect ac-edge-router --format \
    '{{range .Mounts}}{{if eq .Destination "/srv/authority-closers/application/edge-route-releases"}}{{println .Source "|" .Destination "|" .RW}}{{end}}{{end}}'
} | tr -d '\r' | sed '/^$/d')"
expected_route_projection_mount="$edge_route_releases_root | $edge_route_releases_root | false"
[[ "$route_projection_mount" == "$expected_route_projection_mount" ]] || {
  printf 'Running edge router cannot resolve immutable release-owned route selectors.\n' >&2
  exit 1
}
docker exec ac-edge-router caddy validate \
  --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

validate_edge_candidate() {
  local candidate_source="$1" other_environment candidate_dir caddy_image
  candidate_dir="$input_stage/caddy-candidate"
  rm -rf -- "$candidate_dir"
  install -d -m 0755 "$candidate_dir"
  if [[ "$target_environment" == staging ]]; then
    other_environment=production
  else
    other_environment=staging
  fi
  [[ -L "$edge_routes_root/$other_environment.caddy" ]]
  install -m 0644 "$candidate_source" "$candidate_dir/$target_environment.caddy"
  install -m 0644 "$(readlink -f "$edge_routes_root/$other_environment.caddy")" \
    "$candidate_dir/$other_environment.caddy"
  caddy_image="$(docker inspect --format '{{.Image}}' ac-edge-router)"
  [[ "$caddy_image" =~ ^sha256:[0-9a-f]{64}$ ]]
  docker run --rm --pull never --network none --read-only \
    --security-opt no-new-privileges:true --cap-drop ALL --cap-add NET_BIND_SERVICE \
    --user 1000:1000 \
    --tmpfs /config:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000 \
    --tmpfs /data:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000 \
    --volume "$foundation_caddyfile:/etc/caddy/Caddyfile:ro" \
    --volume "$candidate_dir:/etc/caddy/application-routes:ro" \
    --entrypoint caddy "$caddy_image" validate --config /etc/caddy/Caddyfile --adapter caddyfile \
    >/dev/null
}

validate_edge_candidate "$edge_hold_source"
validate_edge_candidate "$edge_route_source"
previous_release=''
if [[ -L "$current_link" ]]; then
  previous_release="$(readlink -f "$current_link")"
  [[ "$(dirname "$previous_release")" == "$releases_root" ]] || {
    printf 'Current application release resolves outside its immutable root.\n' >&2
    exit 1
  }
  [[ "${previous_release##*/}" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'Current application release identity is malformed.\n' >&2
    exit 1
  }
  [[ -f "$previous_release/RELEASE-COMMIT" && \
     "$(<"$previous_release/RELEASE-COMMIT")" == "${previous_release##*/}" ]] || {
    printf 'Current application release marker does not match its immutable path.\n' >&2
    exit 1
  }
  (cd "$previous_release" && sha256sum --check --strict RELEASE-FILES.sha256 >/dev/null)
  python3 "$release_dir/scripts/staging-public-films.py" \
    preflight "$previous_release" "$target_environment"
  python3 "$release_dir/scripts/public-films.py" \
    preflight "$previous_release" "$target_environment"
elif [[ -e "$current_link" ]]; then
  printf 'Current application release path is not a symbolic link.\n' >&2
  exit 1
fi

backup_root="/srv/authority-closers/backups/application/$target_environment"
install -d -m 0750 -o root -g acops "$backup_root"
backup_file="$(mktemp "$backup_root/$(date -u +%Y%m%dT%H%M%SZ)-pre-${release_id}.XXXXXX.dump")"
mutation_started=0
database_mutation_started=0
backup_ready=0
release_committed=0
write_exposure_started=0
forward_recovery_ingress_held=false
forward_recovery_services_stopped=false
forward_recovery_writers_fenced=false
current_switch_armed=0
edge_switch_armed=0
current_tmp=''
evidence_tmp=''
attempt_tmp=''
attempt_file=''

reconcile_edge_router() {
  docker compose --env-file "$foundation_image_env" -f "$foundation_compose_file" \
    up --detach --no-deps --force-recreate --wait --wait-timeout 120 edge-router
  local mounted_edge_routes
  mounted_edge_routes="$({
    docker inspect ac-edge-router --format \
      '{{range .Mounts}}{{if eq .Destination "/etc/caddy/application-routes"}}{{println .Source "|" .RW}}{{end}}{{end}}'
  } | tr -d '\r' | sed '/^$/d')"
  [[ "$mounted_edge_routes" == "$edge_routes_root | false" ]]
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/healthz >/dev/null
}

activate_edge_route() {
  local target_route="$1" selector_tmp
  [[ -f "$target_route" && ! -L "$target_route" ]]
  case "$target_route" in
    "$edge_route_releases_root"/foundation-[0-9a-f]*/"$target_environment".caddy|\
    "$edge_route_releases_root"/[0-9a-f]*/"$target_environment".caddy|\
    "$edge_route_releases_root"/[0-9a-f]*/"$target_environment"-hold.caddy) ;;
    *) printf 'Refusing an edge route outside immutable releases.\n' >&2; return 1 ;;
  esac
  selector_tmp="$edge_routes_root/.${target_environment}-${release_id}.$$"
  [[ ! -e "$selector_tmp" && ! -L "$selector_tmp" ]]
  ln -s "$target_route" "$selector_tmp"
  mv --no-target-directory --force "$selector_tmp" "$edge_route_link"
  edge_switch_armed=1
  [[ "$(readlink -f "$edge_route_link")" == "$target_route" ]]
  reconcile_edge_router
  [[ "$(readlink -f "$edge_route_link")" == "$target_route" ]]
}

restore_edge_route() {
  local selector_tmp
  [[ "$edge_switch_armed" == 1 ]] || return 0
  selector_tmp="$edge_routes_root/.rollback-${target_environment}-${release_id}.$$"
  [[ ! -e "$selector_tmp" && ! -L "$selector_tmp" ]]
  ln -s "$previous_edge_route_target" "$selector_tmp"
  mv --no-target-directory --force "$selector_tmp" "$edge_route_link"
  [[ "$(readlink -f "$edge_route_link")" == "$previous_edge_route_target" ]]
  reconcile_edge_router
  [[ "$(readlink -f "$edge_route_link")" == "$previous_edge_route_target" ]]
  edge_switch_armed=0
}

check_route() {
  local host="$1" path="$2" expected_status="$3" expected_route="$4"
  local expected_location="${5:-}"
  local -a locations=()
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
  if [[ -n "$expected_location" ]]; then
    mapfile -t locations < <(awk 'tolower($1) == "location:" { sub(/^[^:]+:[ \t]*/, ""); sub(/\r$/, ""); print }' "$headers")
    if [[ "${#locations[@]}" -ne 1 ]] || [[
      "${locations[0]}" != "$expected_location" &&
      "${locations[0]}" != "https://$host$expected_location"
    ]]; then
      rm -f -- "$headers" "$body"
      printf 'Route returned an unexpected sign-in destination for %s.\n' "$host" >&2
      return 1
    fi
  fi
  rm -f -- "$headers" "$body"
}

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
  [[ "$write_exposure_started" == 0 ]] || {
    printf 'FAIL  Destructive rollback is forbidden after write exposure.\n' >&2
    return 1
  }
  printf 'ROLLBACK  Restoring %s after failed release %s.\n' "$target_environment" "$release_id" >&2
  if [[ -n "$current_tmp" && -L "$current_tmp" ]]; then
    rm -- "$current_tmp" || rollback_failed=1
  fi
  if [[ -n "$evidence_tmp" && -f "$evidence_tmp" ]]; then
    rm -- "$evidence_tmp" || rollback_failed=1
  fi
  if [[ -n "$attempt_tmp" && -f "$attempt_tmp" ]]; then
    rm -- "$attempt_tmp" || rollback_failed=1
  fi
  if [[ "$backup_ready" == 0 && -f "$backup_file" ]]; then
    # A failed dump/list proof is not a recovery artifact and must not be left
    # behind with a valid-looking immutable backup name.
    rm -- "$backup_file" || rollback_failed=1
  fi
  compose_for "$release_dir" stop --timeout 30 api worker learner-web admin-web coach-web \
    >/dev/null 2>&1 || rollback_failed=1
  if [[ "$database_mutation_started" == 1 ]]; then
    if set_database_writer_access fence; then
      rollback_fenced=1
    else
      rollback_failed=1
    fi
  else
    rollback_fenced=1
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
    restore_current_link || rollback_failed=1
  fi
  if [[ "$rollback_failed" == 0 ]]; then
    restore_edge_route || rollback_failed=1
  fi
  if [[ "$database_mutation_started" == 1 && "$rollback_fenced" == 1 && "$rollback_failed" == 0 ]]; then
    # Reopen only after the backup, application link and matching edge route
    # have all been restored while ingress remained on the release hold.
    set_database_writer_access runtime || rollback_failed=1
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
  printf 'ROLLBACK  Database, application release and matching edge route restored.\n' >&2
}

contain_forward_recovery() {
  local containment_failed=0
  # Exposure has already happened, so containment is forward-only: restore the
  # candidate's reviewed maintenance route and stop every application writer,
  # but never restore the pre-migration database or an older application.
  if ! activate_edge_route "$edge_hold_source"; then
    containment_failed=1
  fi
  if check_route "$api_host" /health/ready 503 "release-hold-$target_environment"; then
    forward_recovery_ingress_held=true
  else
    containment_failed=1
  fi
  if compose_for "$release_dir" stop --timeout 30 \
    api worker learner-web admin-web coach-web; then
    forward_recovery_services_stopped=true
  else
    containment_failed=1
  fi
  if set_database_writer_access fence; then
    forward_recovery_writers_fenced=true
  else
    containment_failed=1
  fi
  [[ "$containment_failed" == 0 ]]
}

record_forward_recovery_required() {
  local recovery_tmp recovery_file recovery_root recovery_suffix
  recovery_root="$application_root/deployments/$target_environment"
  install -d -m 0750 -o root -g acops "$recovery_root" || return 1
  recovery_tmp="$(mktemp "$recovery_root/.forward-recovery-${release_id}.XXXXXX")" || return 1
  recovery_suffix="${recovery_tmp##*.}"
  recovery_file="$recovery_root/$(date -u +%Y%m%dT%H%M%SZ)-${release_id}-forward-recovery-required-${recovery_suffix}.env"
  {
    printf 'AC_STATUS=FORWARD_RECOVERY_REQUIRED\n'
    printf 'AC_ENVIRONMENT=%s\n' "$target_environment"
    printf 'AC_RELEASE_ID=%s\n' "$release_id"
    printf 'AC_WRITE_EXPOSURE_STARTED=true\n'
    printf 'AC_INGRESS_HOLD_RESTORED=%s\n' "$forward_recovery_ingress_held"
    printf 'AC_APPLICATION_SERVICES_STOPPED=%s\n' "$forward_recovery_services_stopped"
    printf 'AC_DATABASE_WRITERS_FENCED=%s\n' "$forward_recovery_writers_fenced"
    printf 'AC_RELEASE_LINK_TARGET=%s\n' "$(readlink -f "$current_link" 2>/dev/null || true)"
    printf 'AC_EDGE_ROUTE_TARGET=%s\n' "$(readlink -f "$edge_route_link" 2>/dev/null || true)"
    printf 'AC_RECOVERY_ACTION=REAPPLY_EXACT_RELEASE\n'
  } > "$recovery_tmp"
  chmod 0640 "$recovery_tmp" || { rm -f -- "$recovery_tmp"; return 1; }
  chown root:acops "$recovery_tmp" || { rm -f -- "$recovery_tmp"; return 1; }
  mv --no-target-directory --no-clobber "$recovery_tmp" "$recovery_file" || {
    rm -f -- "$recovery_tmp"
    return 1
  }
  printf 'FORWARD RECOVERY  Writes may have been accepted; the pre-migration backup will not be restored. Reapply exact release %s.\n' \
    "$release_id" >&2
}

finish() {
  local status=$?
  # Once finalization starts, allow rollback or forward-recovery recording to
  # finish unless the host is forcibly killed. Catchable signals must not recurse.
  trap '' HUP INT TERM
  trap - EXIT
  if [[ "$status" -ne 0 && "$mutation_started" == 1 && "$release_committed" == 0 ]]; then
    if [[ "$write_exposure_started" == 0 ]]; then
      rollback_release || status=1
    else
      contain_forward_recovery || status=1
      record_forward_recovery_required || status=1
    fi
  fi
  if ! cleanup_stages; then
    [[ "$status" -ne 0 ]] || status=1
  fi
  exit "$status"
}
trap finish EXIT

mutation_started=1
activate_edge_route "$edge_hold_source"
check_route "$api_host" /health/ready 503 "release-hold-$target_environment"
writer_release="$release_dir"
if [[ -n "$previous_release" ]]; then
  writer_release="$previous_release"
fi
compose_for "$writer_release" stop --timeout 30 api worker
database_mutation_started=1
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
check_route "$api_host" /health/ready 503 "release-hold-$target_environment"

# Finalize the append-only prepared record while runtime database access and
# every application service remain held. Subsequent startup still occurs behind
# the twice-proven maintenance route and with the worker stopped.
evidence_root="$application_root/deployments/$target_environment"
install -d -m 0750 -o root -g acops "$evidence_root"
attempt_tmp="$(mktemp "$evidence_root/.prepared-${release_id}.XXXXXX")"
attempt_file="$evidence_root/$(date -u +%Y%m%dT%H%M%SZ)-${release_id}-prepared-${attempt_tmp##*.}.env"
{
  printf 'AC_STATUS=PREPARED_BEFORE_WRITE_EXPOSURE\n'
  printf 'AC_ENVIRONMENT=%s\n' "$target_environment"
  printf 'AC_RELEASE_ID=%s\n' "$release_id"
  printf 'AC_PREVIOUS_RELEASE=%s\n' "${previous_release##*/}"
  printf 'AC_PREVIOUS_EDGE_ROUTE=%s\n' "$previous_edge_route_target"
  printf 'AC_TARGET_EDGE_ROUTE=%s\n' "$edge_route_source"
  printf 'AC_PRE_MIGRATION_BACKUP=%s\n' "$backup_file"
} > "$attempt_tmp"
chmod 0640 "$attempt_tmp"
chown root:acops "$attempt_tmp"
mv --no-target-directory --no-clobber "$attempt_tmp" "$attempt_file"
attempt_tmp=''

set_database_writer_access runtime
compose_for "$release_dir" up --detach --remove-orphans --wait --wait-timeout 180 \
  api learner-web admin-web coach-web
check_route "$api_host" /health/ready 503 "release-hold-$target_environment"

current_tmp="$application_root/.current-${target_environment}-${release_id}.$$"
ln -s "$release_dir" "$current_tmp"
current_switch_armed=1
mv --no-target-directory --force "$current_tmp" "$current_link"
current_tmp=''
[[ "$(readlink -f "$current_link")" == "$release_dir" ]]

# From this point the API ingress or worker may accept writes. No subsequent
# failure may restore the pre-migration backup or an older application/route.
# Recovery is forward-only by reapplying this exact immutable release.
write_exposure_started=1
activate_edge_route "$edge_route_source"
check_route "$learner_host" / 200 "learner-$target_environment"
check_route "$admin_host" / 307 "admin-$target_environment" /login
check_route "$admin_host" /login 200 "admin-$target_environment"
check_route "$coach_host" / 307 "coach-$target_environment" /login
check_route "$coach_host" /login 200 "coach-$target_environment"
check_route "$api_host" /health/ready 200 "api-$target_environment"
compose_for "$release_dir" up --detach --no-deps --wait --wait-timeout 180 worker

evidence_tmp="$(mktemp "$evidence_root/.deployment-${release_id}.XXXXXX")"
evidence_file="$evidence_root/$(date -u +%Y%m%dT%H%M%SZ)-${release_id}-${evidence_tmp##*.}.env"
{
  printf 'AC_ENVIRONMENT=%s\n' "$target_environment"
  printf 'AC_STATUS=COMMITTED\n'
  printf 'AC_RELEASE_ID=%s\n' "$release_id"
  printf 'AC_PREPARED_EVIDENCE=%s\n' "$attempt_file"
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
  printf 'AC_COACH_IMAGE=%s\n' "$AC_COACH_IMAGE"
  printf 'AC_COACH_REGISTRY_DIGEST=%s\n' "$AC_COACH_REGISTRY_DIGEST"
  printf 'AC_COACH_TRANSPORT_DIGEST=%s\n' "$AC_COACH_TRANSPORT_DIGEST"
  printf 'AC_EDGE_ROUTE=%s\n' "$edge_route_source"
} > "$evidence_tmp"
chmod 0640 "$evidence_tmp"
chown root:acops "$evidence_tmp"
mv --no-target-directory --no-clobber "$evidence_tmp" "$evidence_file"
evidence_tmp=''
release_committed=1

printf 'PASS  %s now runs exact release %s (external side effects: %s; email provider: %s).\n' \
  "$target_environment" "$release_id" "$external_side_effects_status" "$email_provider"
