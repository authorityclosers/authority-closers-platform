#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

# Never feed an untrusted decimal directly to Bash arithmetic. Bash integers
# are signed and platform-sized, so a large metric can otherwise wrap and
# make an over-ceiling total appear small. Values are bounded before string
# work, and totals are saturated at ceiling + 1.
DECIMAL_MAX_DIGITS=4096

decimal_normalize() {
  local value="$1"
  local label="$2"

  (( ${#value} <= DECIMAL_MAX_DIGITS )) || {
    printf 'R2 %s exceeds the bounded decimal length.\n' "$label" >&2
    return 1
  }
  [[ "$value" =~ ^[0-9]+$ ]] || {
    printf 'R2 %s must be a non-negative decimal integer.\n' "$label" >&2
    return 1
  }
  while [[ ${#value} -gt 1 && ${value:0:1} == 0 ]]; do
    value="${value:1}"
  done
  printf '%s' "$value"
}

decimal_gt() {
  local left="$1"
  local right="$2"

  if (( ${#left} != ${#right} )); then
    (( ${#left} > ${#right} ))
  else
    [[ "$left" > "$right" ]]
  fi
}

decimal_increment() {
  local value="$1"
  local result=''
  local carry=1
  local digit
  local index

  for ((index=${#value}-1; index>=0; index--)); do
    digit="${value:index:1}"
    if (( carry == 1 )); then
      case "$digit" in
        9) result="0${result}" ;;
        0) result="1${result}"; carry=0 ;;
        1) result="2${result}"; carry=0 ;;
        2) result="3${result}"; carry=0 ;;
        3) result="4${result}"; carry=0 ;;
        4) result="5${result}"; carry=0 ;;
        5) result="6${result}"; carry=0 ;;
        6) result="7${result}"; carry=0 ;;
        7) result="8${result}"; carry=0 ;;
        8) result="9${result}"; carry=0 ;;
      esac
    else
      result="${digit}${result}"
    fi
  done
  (( carry == 1 )) && result="1${result}"
  printf '%s' "$result"
}

decimal_add_capped() {
  local left="$1"
  local right="$2"
  local ceiling="$3"
  local result=''
  local carry=0
  local left_digit=0
  local right_digit=0
  local index_left=$(( ${#left} - 1 ))
  local index_right=$(( ${#right} - 1 ))
  local sum
  local digit

  if decimal_gt "$left" "$ceiling" || decimal_gt "$right" "$ceiling"; then
    decimal_increment "$ceiling"
    return
  fi

  while (( index_left >= 0 || index_right >= 0 || carry == 1 )); do
    left_digit=0
    right_digit=0
    if (( index_left >= 0 )); then
      left_digit="${left:index_left:1}"
      index_left=$((index_left - 1))
    fi
    if (( index_right >= 0 )); then
      right_digit="${right:index_right:1}"
      index_right=$((index_right - 1))
    fi
    # These operands are individual decimal digits, never whole inputs.
    sum=$((left_digit + right_digit + carry))
    digit=$((sum % 10))
    carry=$((sum / 10))
    result="${digit}${result}"
  done

  if decimal_gt "$result" "$ceiling"; then
    decimal_increment "$ceiling"
  else
    printf '%s' "$result"
  fi
}

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
R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES=''
R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT=''
R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS=''

while IFS='=' read -r key value; do
  key="${key%$'\r'}"
  value="${value%$'\r'}"
  [[ -z "$key" || "$key" == \#* ]] && continue
  case "$key" in
    R2_MAX_STANDARD_BYTES|R2_MAX_CLASS_A_MONTH|R2_MAX_CLASS_B_MONTH|R2_FORBID_INFREQUENT_ACCESS|R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES|R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT|R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS)
      normalized_policy_value="$(decimal_normalize "$value" "$key")" || exit 1
      printf -v "$key" '%s' "$normalized_policy_value"
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

# These bounds are enforced by the PostgreSQL backup writer. This evaluator
# still requires and validates them so one shared policy cannot drift.
: "$R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES"
: "$R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT"
: "$R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS"

for key in \
  R2_MAX_STANDARD_BYTES \
  R2_MAX_CLASS_A_MONTH \
  R2_MAX_CLASS_B_MONTH \
  R2_FORBID_INFREQUENT_ACCESS \
  R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES \
  R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT \
  R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS; do
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

mapfile -t storage_values < <(jq --exit-status --raw-output '[
  .result.standard.uploaded.payloadSize,
  .result.standard.uploaded.metadataSize,
  .result.standard.published.payloadSize,
  .result.standard.published.metadataSize,
  .result.infrequentAccess.uploaded.payloadSize,
  .result.infrequentAccess.uploaded.metadataSize,
  .result.infrequentAccess.published.payloadSize,
  .result.infrequentAccess.published.metadataSize
] | .[] | tostring' "$storage_file")
[[ ${#storage_values[@]} -eq 8 ]] || {
  printf 'FAIL  R2 storage metrics could not be extracted safely.\n' >&2
  exit 1
}

standard_bytes=0
for index in 0 1 2 3; do
  storage_value="${storage_values[index]%$'\r'}"
  storage_value="$(decimal_normalize "$storage_value" "storage metric")" || exit 1
  standard_bytes="$(decimal_add_capped "$standard_bytes" "$storage_value" "$R2_MAX_STANDARD_BYTES")"
done

infrequent_bytes=0
for index in 4 5 6 7; do
  storage_value="${storage_values[index]%$'\r'}"
  storage_value="$(decimal_normalize "$storage_value" "storage metric")" || exit 1
  infrequent_bytes="$(decimal_add_capped "$infrequent_bytes" "$storage_value" "$R2_MAX_STANDARD_BYTES")"
done

projected_bytes="$(decimal_normalize "${R2_PROJECTED_ADDITIONAL_BYTES:-0}" "R2_PROJECTED_ADDITIONAL_BYTES")" || exit 1
projected_standard_bytes="$(decimal_add_capped "$standard_bytes" "$projected_bytes" "$R2_MAX_STANDARD_BYTES")"

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
  action="${action%$'\r'}"
  requests="${requests%$'\r'}"
  requests="$(decimal_normalize "$requests" "operation count for $action")" || exit 1
  case "$action" in
    ListBuckets|PutBucket|CreateBucket|ListObjects|ListObjectsV2|PutObject|CopyObject|CompleteMultipartUpload|CreateMultipartUpload|LifecycleStorageTierTransition|ListMultipartUploads|UploadPart|UploadPartCopy|ListParts|PutBucketEncryption|PutBucketCors|PutBucketLifecycleConfiguration)
      class_a="$(decimal_add_capped "$class_a" "$requests" "$R2_MAX_CLASS_A_MONTH")"
      ;;
    HeadBucket|HeadObject|GetObject|UsageSummary|GetBucketEncryption|GetBucketLocation|GetBucketCors|GetBucketLifecycleConfiguration)
      class_b="$(decimal_add_capped "$class_b" "$requests" "$R2_MAX_CLASS_B_MONTH")"
      ;;
    DeleteObject|DeleteBucket|AbortMultipartUpload|LifecycleDeletion)
      ;;
    *)
      printf 'UNKNOWN  R2 operation type %s (%s requests).\n' "$action" "$requests" >&2
      [[ "$requests" == 0 ]] || unknown=1
      ;;
  esac
done < <(jq --raw-output '
  .data.viewer.accounts[0].r2OperationsAdaptiveGroups[]
  | [.dimensions.actionType, .sum.requests]
  | @tsv
' "$operations_file")

failures=0

if decimal_gt "$standard_bytes" "$R2_MAX_STANDARD_BYTES"; then
  printf 'FAIL  Standard R2 bytes %s exceed policy ceiling %s.\n' \
    "$standard_bytes" "$R2_MAX_STANDARD_BYTES" >&2
  failures=$((failures + 1))
fi

if decimal_gt "$projected_standard_bytes" "$R2_MAX_STANDARD_BYTES"; then
  printf 'FAIL  Projected Standard R2 bytes %s exceed policy ceiling %s.\n' \
    "$projected_standard_bytes" "$R2_MAX_STANDARD_BYTES" >&2
  failures=$((failures + 1))
fi

if [[ "$R2_FORBID_INFREQUENT_ACCESS" == 1 ]] && [[ "$infrequent_bytes" != 0 ]]; then
  printf 'FAIL  Infrequent Access usage is forbidden but %s bytes exist.\n' \
    "$infrequent_bytes" >&2
  failures=$((failures + 1))
fi

if decimal_gt "$class_a" "$R2_MAX_CLASS_A_MONTH"; then
  printf 'FAIL  Class A operations %s exceed policy ceiling %s.\n' \
    "$class_a" "$R2_MAX_CLASS_A_MONTH" >&2
  failures=$((failures + 1))
fi

if decimal_gt "$class_b" "$R2_MAX_CLASS_B_MONTH"; then
  printf 'FAIL  Class B operations %s exceed policy ceiling %s.\n' \
    "$class_b" "$R2_MAX_CLASS_B_MONTH" >&2
  failures=$((failures + 1))
fi

if (( unknown == 1 )); then
  printf 'FAIL  Unknown R2 operations prevent a safe cost classification.\n' >&2
  failures=$((failures + 1))
fi

printf 'R2 usage: standard_bytes=%s infrequent_bytes=%s class_a=%s class_b=%s projected_standard_bytes=%s\n' \
  "$standard_bytes" "$infrequent_bytes" "$class_a" "$class_b" "$projected_standard_bytes"

((failures == 0)) || exit 1
printf 'PASS  R2 usage is inside the conservative free-tier operating envelope.\n'
