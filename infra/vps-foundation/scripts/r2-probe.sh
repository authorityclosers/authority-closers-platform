#!/usr/bin/env bash
set -euo pipefail

: "${R2_ENDPOINT:?Set R2_ENDPOINT}"
: "${R2_ACCESS_KEY_ID:?Set R2_ACCESS_KEY_ID}"
: "${R2_SECRET_ACCESS_KEY:?Set R2_SECRET_ACCESS_KEY}"

backup_bucket="${R2_BACKUP_BUCKET:-authority-closers-backups-prod}"
object_bucket="${R2_OBJECT_BUCKET:-authority-closers-objects-prod}"

remote_name="ac_r2_probe"
remote_prefix="${remote_name^^}"
export "RCLONE_CONFIG_${remote_prefix}_TYPE=s3"
export "RCLONE_CONFIG_${remote_prefix}_PROVIDER=Cloudflare"
export "RCLONE_CONFIG_${remote_prefix}_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID"
export "RCLONE_CONFIG_${remote_prefix}_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY"
export "RCLONE_CONFIG_${remote_prefix}_ENDPOINT=$R2_ENDPOINT"
export "RCLONE_CONFIG_${remote_prefix}_REGION=auto"
export "RCLONE_CONFIG_${remote_prefix}_NO_CHECK_BUCKET=true"

rclone lsf "$remote_name:$backup_bucket" --max-depth 1 >/dev/null
rclone lsf "$remote_name:$object_bucket" --max-depth 1 >/dev/null

probe_targets=()
cleanup() {
  local target
  for target in "${probe_targets[@]}"; do
    rclone deletefile "$target" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

probe_bucket() {
  local bucket="$1"
  local probe_key
  local probe_target
  local expected='authority-closers-r2-probe-ok'
  local actual

  probe_key="foundation-probes/$(date -u +%Y%m%dT%H%M%SZ)-$$.txt"
  probe_target="$remote_name:$bucket/$probe_key"
  probe_targets+=("$probe_target")
  printf '%s' "$expected" | rclone rcat "$probe_target"
  actual="$(rclone cat "$probe_target")"
  [[ "$actual" == "$expected" ]]
  rclone deletefile "$probe_target"
}

probe_bucket "$backup_bucket"
probe_bucket "$object_bucket"
probe_targets=()
trap - EXIT

printf 'PASS  R2 buckets exist and reversible probes succeeded in both buckets.\n'
