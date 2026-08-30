#!/usr/bin/env bash

# dpkg-query returns success for package database stubs whose desired/current
# state is "unknown/not-installed".  Treat only a fully installed package as
# present so a removed Ubuntu Docker package cannot block the Docker CE
# baseline merely because dpkg retained a name-only record.
ac_os_package_is_installed() {
  local package=$1
  local status

  status="$(dpkg-query -W -f='${db:Status-Abbrev}' "$package" 2>/dev/null || true)"
  [[ "$status" == 'ii ' ]]
}

# apt-mark accepts architecture-qualified package names but reports native
# architecture holds without the suffix.  Normalize policy names before set
# membership checks so rollback can always remove exactly the holds it added.
ac_os_package_hold_name() {
  local package=$1
  printf '%s\n' "${package%%:*}"
}

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
