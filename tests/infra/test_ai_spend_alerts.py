"""AI spend at its environment cap: one owner line a day, and only on production.

Owner rule: Telegram carries releases and incidents only. A production environment
cap stops background AI, so it is an incident; on staging and development the same
stop shows in Admin -> AI spend alone. The notifier is a local fake.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-call-data"
LINES = "\n".join(
    [
        '{"started": "automatic:call-data", "apply": true}',
        '{"stopped": "ai_spend_daily_cap", "feature": "call_data_fast", "spent_inr": "1000.25",'
        ' "cap_inr": 1000}',
        '{"stopped": "ai_spend_daily_cap", "feature": "call_data_deep", "spent_inr": "1000.25",'
        ' "cap_inr": 1000}',
        '{"stopped": "ai_spend_background_off", "feature": "call_data_fast", "spent_inr": "0.00",'
        ' "cap_inr": 0}',
        '{"stopped": "ai_spend_monthly_cap", "feature": "call_data_fast", "spent_inr": "8000",'
        ' "cap_inr": 8000}',
    ]
)


def _forward(tmp_path: Path, environment: str) -> list[str]:
    # The launcher starts the notifier with an empty environment: one folder per run.
    folder = tmp_path / environment
    folder.mkdir()
    record = folder / "sent.txt"
    fake = folder / "notify"
    fake.write_text(f"#!/bin/bash\nprintf '%s\\n' \"$1\" >> '{record}'\n")
    fake.chmod(0o755)
    for _ in range(2):  # a restart the same day sends nothing new
        subprocess.run(  # noqa: S603
            ["bash", "-c", 'source "$1"; forward_alerts "$2"', "test", str(SCRIPT), environment],  # noqa: S607
            input=LINES + "\n",
            capture_output=True,
            text=True,
            check=True,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "NOTIFY": str(fake),
                "CALL_DATA_STATE": str(folder),
            },
            timeout=60,
        )
    return record.read_text().splitlines() if record.exists() else []


def test_production_cap_is_one_incident_line_a_day(tmp_path: Path) -> None:
    assert _forward(tmp_path, "production") == [
        "Sales X-Ray (production): AI spend reached its daily cap (Rs 1000.25). Background AI"
        " jobs wait, nothing is lost and customer calls are not affected."
        " Admin -> AI spend -> Raise.",
        "Sales X-Ray (production): AI spend reached its monthly cap (Rs 8000). Background AI"
        " jobs wait, nothing is lost and customer calls are not affected."
        " Admin -> AI spend -> Raise.",
    ]


def test_staging_and_development_caps_stay_in_admin(tmp_path: Path) -> None:
    assert _forward(tmp_path, "staging") == []
    assert _forward(tmp_path, "development-live") == []
