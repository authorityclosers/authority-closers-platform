#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 3 ]] || {
  printf 'Usage: %s STORAGE_JSON OPERATIONS_JSON POLICY_FILE\n' "$0" >&2
  exit 2
}

storage_file="$1"
operations_file="$2"
policy_file="$3"

for path in "$storage_file" "$operations_file" "$policy_file"; do
  [[ -r "$path" ]] || { printf 'Required input is not readable: %s\n' "$path" >&2; exit 1; }
done

R2_MAX_STANDARD_BYTES=''
R2_MAX_CLASS_A_MONTH=''
R2_MAX_CLASS_B_MONTH=''
R2_FORBID_INFREQUENT_ACCESS=''

while IFS='=' read -r key value; do
  key="${key%$'\r'}"
  value="${value%$'\r'}"
  [[ -z "$key" || "$key" == \#* ]] && continue
  case "$key" in
    R2_MAX_STANDARD_BYTES|R2_MAX_CLASS_A_MONTH|R2_MAX_CLASS_B_MONTH|R2_FORBID_INFREQUENT_ACCESS)
      printf -v "$key" '%s' "$value"
      ;;
    R2_BACKUP_BUCKET|R2_OBJECT_BUCKET)
      [[ "$value" =~ ^[a-z0-9][a-z0-9-]{1,62}$ ]] || {
        printf 'Invalid bucket name in R2 policy: %s\n' "$key" >&2
        exit 1
      }
      ;;
    *)
      printf 'Unknown assignment in R2 policy: %s\n' "$key" >&2
      exit 1
      ;;
  esac
done < "$policy_file"

for key in \
  R2_MAX_STANDARD_BYTES \
  R2_MAX_CLASS_A_MONTH \
  R2_MAX_CLASS_B_MONTH \
  R2_FORBID_INFREQUENT_ACCESS; do
  value="${!key}"
  [[ "$value" =~ ^[0-9]+$ ]] || {
    printf 'R2 policy value must be a non-negative integer: %s\n' "$key" >&2
    exit 1
  }
done
[[ "$R2_FORBID_INFREQUENT_ACCESS" == 0 || "$R2_FORBID_INFREQUENT_ACCESS" == 1 ]] || {
  printf 'R2_FORBID_INFREQUENT_ACCESS must be 0 or 1.\n' >&2
  exit 1
}

jq --exit-status '
  def uint: type == "number" and . >= 0 and floor == .;
  (.success == true) and
  (.result | type == "object") and
  (.result.standard | type == "object") and
  (.result.infrequentAccess | type == "object") and
  ([
    .result.standard.uploaded.payloadSize,
    .result.standard.uploaded.metadataSize,
    .result.standard.published.payloadSize,
    .result.standard.published.metadataSize,
    .result.infrequentAccess.uploaded.payloadSize,
    .result.infrequentAccess.uploaded.metadataSize,
    .result.infrequentAccess.published.payloadSize,
    .result.infrequentAccess.published.metadataSize
  ] | all(.[]; uint))
' "$storage_file" >/dev/null || {
  printf 'FAIL  R2 storage metrics are missing, malformed, or non-numeric.\n' >&2
  exit 1
}

standard_bytes="$(jq --exit-status --raw-output '[
  .result.standard.uploaded.payloadSize,
  .result.standard.uploaded.metadataSize,
  .result.standard.published.payloadSize,
  .result.standard.published.metadataSize
] | add' "$storage_file")"

infrequent_bytes="$(jq --exit-status --raw-output '[
  .result.infrequentAccess.uploaded.payloadSize,
  .result.infrequentAccess.uploaded.metadataSize,
  .result.infrequentAccess.published.payloadSize,
  .result.infrequentAccess.published.metadataSize
] | add' "$storage_file")"

jq --exit-status '
  def uint: type == "number" and . >= 0 and floor == .;
  (((.errors // []) | type == "array") and ((.errors // []) | length == 0)) and
  (.data.viewer.accounts | type == "array" and length == 1) and
  (.data.viewer.accounts[0] | has("r2OperationsAdaptiveGroups")) and
  (.data.viewer.accounts[0].r2OperationsAdaptiveGroups | type == "array") and
  (all(.data.viewer.accounts[0].r2OperationsAdaptiveGroups[];
    (.dimensions | type == "object") and
    (.dimensions.actionType | type == "string" and length > 0) and
    (.sum | type == "object") and
    (.sum.requests | uint)
  ))
' "$operations_file" >/dev/null || {
  printf 'FAIL  R2 operation metrics have no unique account dataset or contain malformed groups.\n' >&2
  exit 1
}

class_a=0
class_b=0
unknown=0

while IFS=$'\t' read -r action requests; do
  [[ "$requests" =~ ^[0-9]+$ ]] || {
    printf 'FAIL  R2 operation count is not an integer for %s.\n' "$action" >&2
    exit 1
  }
  case "$action" in
    ListBuckets|PutBucket|CreateBucket|ListObjects|ListObjectsV2|PutObject|CopyObject|CompleteMultipartUpload|CreateMultipartUpload|LifecycleStorageTierTransition|ListMultipartUploads|UploadPart|UploadPartCopy|ListParts|PutBucketEncryption|PutBucketCors|PutBucketLifecycleConfiguration)
      class_a=$((class_a + requests))
      ;;
    HeadBucket|HeadObject|GetObject|UsageSummary|GetBucketEncryption|GetBucketLocation|GetBucketCors|GetBucketLifecycleConfiguration)
      class_b=$((class_b + requests))
      ;;
    DeleteObject|DeleteBucket|AbortMultipartUpload|LifecycleDeletion)
      ;;
    *)
      printf 'UNKNOWN  R2 operation type %s (%s requests).\n' "$action" "$requests" >&2
      unknown=$((unknown + requests))
      ;;
  esac
done < <(jq --raw-output '
  .data.viewer.accounts[0].r2OperationsAdaptiveGroups[]
  | [.dimensions.actionType, .sum.requests]
  | @tsv
' "$operations_file")

failures=0

if ((standard_bytes > R2_MAX_STANDARD_BYTES)); then
  printf 'FAIL  Standard R2 bytes %s exceed policy ceiling %s.\n' \
    "$standard_bytes" "$R2_MAX_STANDARD_BYTES" >&2
  failures=$((failures + 1))
fi

if ((R2_FORBID_INFREQUENT_ACCESS == 1 && infrequent_bytes > 0)); then
  printf 'FAIL  Infrequent Access usage is forbidden but %s bytes exist.\n' \
    "$infrequent_bytes" >&2
  failures=$((failures + 1))
fi

if ((class_a > R2_MAX_CLASS_A_MONTH)); then
  printf 'FAIL  Class A operations %s exceed policy ceiling %s.\n' \
    "$class_a" "$R2_MAX_CLASS_A_MONTH" >&2
  failures=$((failures + 1))
fi

if ((class_b > R2_MAX_CLASS_B_MONTH)); then
  printf 'FAIL  Class B operations %s exceed policy ceiling %s.\n' \
    "$class_b" "$R2_MAX_CLASS_B_MONTH" >&2
  failures=$((failures + 1))
fi

if ((unknown > 0)); then
  printf 'FAIL  Unknown R2 operations prevent a safe cost classification.\n' >&2
  failures=$((failures + 1))
fi

printf 'R2 usage: standard_bytes=%s infrequent_bytes=%s class_a=%s class_b=%s\n' \
  "$standard_bytes" "$infrequent_bytes" "$class_a" "$class_b"

((failures == 0)) || exit 1
printf 'PASS  R2 usage is inside the conservative free-tier operating envelope.\n'
