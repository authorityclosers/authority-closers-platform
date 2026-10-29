"""Application logs outlive a release: journald, not the container's own log (28 Oct 2026)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra/application/compose.yaml"
SERVICES = ("migrate", "api", "intake-spool", "worker", "learner-web", "admin-web", "coach-web")


def test_application_services_log_to_the_journal() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    for name in SERVICES:
        logging = services[name]["logging"]
        assert logging == {"driver": "journald", "options": {"tag": "{{.Name}}"}}, name
