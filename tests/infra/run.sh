#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$script_dir/test-r2-usage-evaluate.sh"
bash "$script_dir/test-ufw-lockdown-parser.sh"
bash "$script_dir/test-docker-firewall-order.sh"
bash "$script_dir/test-infisical-bootstrap.sh"
bash "$script_dir/test-os-baseline-policy.sh"
bash "$script_dir/test-release-install.sh"
bash "$script_dir/test-security-invariants.sh"
