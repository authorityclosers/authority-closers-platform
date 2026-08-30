#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$script_dir/test-r2-usage-evaluate.sh"
python3 -m pytest "$script_dir/test_postgres_backup.py"
python3 -m pytest "$script_dir/test_postgres_restore_proof.py"
bash "$script_dir/test-ufw-lockdown-parser.sh"
bash "$script_dir/test-docker-firewall-order.sh"
bash "$script_dir/test-infisical-bootstrap.sh"
bash "$script_dir/test-os-baseline-policy.sh"
bash "$script_dir/test-os-baseline-transaction.sh"
bash "$script_dir/test-release-install.sh"
bash "$script_dir/test-security-invariants.sh"
