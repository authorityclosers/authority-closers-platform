#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

run_root_restore_proof_tests() {
  local test_files=(
    "$script_dir/test_postgres_restore_proof.py"
    "$script_dir/test_capability_backup_parity.py"
  )
  local python="$repo_root/.venv/bin/python"
  if [[ ! -x "$python" ]]; then
    printf 'The locked project Python environment is required for root restore-proof tests.\n' >&2
    return 1
  fi
  if ((EUID == 0)); then
    PYTHONDONTWRITEBYTECODE=1 "$python" -m pytest -p no:cacheprovider "${test_files[@]}"
    return
  fi
  command -v sudo >/dev/null 2>&1 || {
    printf 'Root access is required for restore-proof ownership tests.\n' >&2
    return 1
  }
  sudo env PYTHONDONTWRITEBYTECODE=1 \
    "$python" -m pytest -p no:cacheprovider "${test_files[@]}"
}

bash "$script_dir/test-r2-usage-evaluate.sh"
uv run pytest "$script_dir/test_postgres_backup.py"
run_root_restore_proof_tests
bash "$script_dir/test-ufw-lockdown-parser.sh"
bash "$script_dir/test-docker-firewall-order.sh"
bash "$script_dir/test-infisical-bootstrap.sh"
bash "$script_dir/test-os-baseline-policy.sh"
bash "$script_dir/test-os-baseline-transaction.sh"
bash "$script_dir/test-release-install.sh"
bash "$script_dir/test-security-invariants.sh"
