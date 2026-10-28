#!/usr/bin/env python3
"""Owner/operator installer. Plan by default; no credential provisioning or S3 policy edits."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--approval-record")
    args = p.parse_args()
    config = Path(args.config)
    c = json.loads(config.read_text())
    pin = hashlib.sha256(config.read_bytes()).hexdigest()
    if not args.execute:
        print(
            json.dumps(
                {
                    "execute": False,
                    "config_sha256": pin,
                    "steps": [
                        "install files",
                        "capture now",
                        "encrypted archive now",
                        "enable both timers",
                    ],
                }
            )
        )
        return
    approval = json.loads(Path(args.approval_record or "/nonexistent").read_text())
    if (
        approval.get("config_sha256") != pin
        or approval.get("action") != "install-backups"
        or not approval.get("owner_record")
    ):
        raise ValueError("exact owner/operator approval record required")
    if c["backup_root"] != "/srv/authority-closers/backups/aws":
        raise ValueError("service writable root mismatch")
    for name in ["encryption_certificate", "archive_credentials_helper"]:
        if not Path(c[name]).is_file():
            raise ValueError("public certificate and credential helper must be provisioned")
    root = Path(__file__).resolve().parent
    lib = Path("/usr/local/lib/ac-cutover")
    lib.mkdir(parents=True, exist_ok=True, mode=0o755)
    for name in ["backup.py", "endpoint.py", "recover-archive.py", "install-backups.py"]:
        if (root / name).resolve() != (lib / name).resolve():
            shutil.copyfile(root / name, lib / name)
        (lib / name).chmod(0o644)
    target = Path("/etc/authority-closers/aws-backup.json")
    shutil.copyfile(config, target)
    target.chmod(0o600)
    for unit in (root / "systemd").iterdir():
        shutil.copyfile(unit, Path("/etc/systemd/system") / unit.name)
    commands = [
        ["systemctl", "daemon-reload"],
        ["python3", str(lib / "backup.py"), "capture", "--config", str(target)],
        ["python3", str(lib / "backup.py"), "archive", "--config", str(target)],
        [
            "systemctl",
            "enable",
            "--now",
            "ac-aws-backup@capture.timer",
            "ac-aws-backup@archive.timer",
        ],
    ]
    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603 -- fixed installer argv
        if result.returncode:
            raise RuntimeError("backup admission failed; do not open production")
    print("initial dump and encrypted upload verified; both timers enabled")


if __name__ == "__main__":
    main()
