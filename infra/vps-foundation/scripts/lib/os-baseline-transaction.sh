#!/usr/bin/env bash

# Return the only safe failure disposition for an attempted OS-baseline
# transition.  A prior baseline may be advertised again only when the complete
# live package graph is byte-for-byte identical to the rollback reference.
ac_os_baseline_failure_disposition() {
  local rollback_reference=$1
  local live_graph=$2
  local cmp_status

  if cmp --silent -- "$rollback_reference" "$live_graph"; then
    printf '%s\n' 'rollback-safe'
    return 0
  else
    cmp_status=$?
  fi
  if [[ "$cmp_status" -eq 1 ]]; then
    printf '%s\n' 'recovery-required'
    return 0
  fi
  return "$cmp_status"
}
