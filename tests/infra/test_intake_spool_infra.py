"""Release-safe intake (owner, 27 Oct 2026; docs/product/lead-desk/release-safe-intake.md).

During a release's hold the edge sends the website-form capture posts to the intake
spool, a small service of the API image with no database and no secrets. The release
starts it before the hold, and the API files what it kept.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.infra.test_admin_internal_transport import ROOT, _render_compose

APPLICATION = ROOT / "infra" / "application"
INSTALLER = (APPLICATION / "scripts" / "install-application-release.sh").read_text(encoding="utf-8")
SPOOL_TARGET = "/var/lib/ac-intake-spool"


def _bind(service: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (str(volume["source"]), str(volume["target"]))
        for volume in service.get("volumes", [])
        if volume.get("type") == "bind"
    ]


@pytest.mark.parametrize("profile", ["staging", "production"])
def test_the_spool_runs_the_api_image_with_no_database_and_no_secrets(profile: str) -> None:
    services = _render_compose(profile, enabled_profiles=("release",))["services"]
    assert isinstance(services, dict)
    spool, api = services["intake-spool"], services["api"]
    assert spool["image"] == api["image"]
    assert spool["command"] == ["python", "-m", "ac_platform.lead_desk.spool", "serve"]
    assert spool["read_only"] is True
    assert spool["cap_drop"] == ["ALL"]
    # No secrets: where to keep leads, and the edge router's address for the rate.
    assert set(spool["environment"]) == {
        "AC_ENVIRONMENT",
        "AC_INTAKE_SPOOL_ROOT",
        "AC_TRUSTED_PROXY_ADDRESSES",
    }
    trusted = spool["environment"]["AC_TRUSTED_PROXY_ADDRESSES"]
    assert trusted == api["environment"]["AC_TRUSTED_PROXY_ADDRESSES"]
    assert spool["environment"]["AC_INTAKE_SPOOL_ROOT"] == SPOOL_TARGET
    # Only the edge reaches it, under the API's alias with "-intake".
    assert set(spool["networks"]) == {"edge"}
    assert spool["networks"]["edge"]["aliases"] == [f"ac-{profile}-api-intake"]
    root = f"/srv/authority-closers/application/intake-spool/{profile}"
    assert _bind(spool) == [(root, SPOOL_TARGET)]
    # The release prepares the folder; Docker never makes it (it would be root's). Compose
    # leaves the false value out of its rendering, so the file itself is read.
    compose = (APPLICATION / "compose.yaml").read_text(encoding="utf-8")
    spool_block = compose[compose.index("  intake-spool:\n") : compose.index("  worker:\n")]
    assert spool_block.count("create_host_path: false") == 1
    api_block = compose[compose.index("  api:\n") : compose.index("  intake-spool:\n")]
    assert api_block.count("create_host_path: false") == 1
    # The API reads the same folder to file what the spool kept.
    assert (root, SPOOL_TARGET) in _bind(api)
    assert api["environment"]["AC_INTAKE_SPOOL_ROOT"] == SPOOL_TARGET


@pytest.mark.parametrize(
    ("environment", "host"),
    [
        ("production", "salesxray.authorityclosers.com"),
        ("staging", "salesxray-staging.authorityclosers.com"),
    ],
)
def test_the_hold_sends_only_capture_posts_to_the_spool(environment: str, host: str) -> None:
    hold = (APPLICATION / "edge-routes" / f"{environment}-hold.caddy").read_text(encoding="utf-8")
    intake = hold.index(f"handle @{environment}_release_intake {{")
    held = hold.index(f"handle @{environment}_release_hold {{")
    # The intake route comes first, so it is the one that answers a capture post.
    assert intake < held
    matcher = hold[hold.index(f"@{environment}_release_intake {{") : intake]
    assert f"host {host}\n" in matcher
    assert "method POST\n" in matcher
    assert "path_regexp ^/v1/lead-desk/capture/[0-9a-fA-F-]+(/google-ads)?$" in matcher
    assert f"reverse_proxy ac-{environment}-api-intake:8080" in hold[intake:held]
    # Everything else still gets the hold's 503.
    assert 'header Retry-After "30"' in hold[held:]
    assert " 503" in hold[held:]


def test_the_release_starts_the_spool_before_the_hold_and_never_stops_on_it() -> None:
    deployment = INSTALLER.split("trap finish EXIT", maxsplit=1)[1]
    start = "up --detach --no-deps --wait --wait-timeout 60 intake-spool"
    assert deployment.index("prepare_intake_spool_root\n") < deployment.index(start)
    assert deployment.index(start) < deployment.index('activate_edge_route "$edge_hold_source"')
    assert deployment.index(start) < deployment.index("mutation_started=1")
    # A spool that won't start leaves today's 503; it never stops the release.
    assert f'if ! compose_for "$release_dir" {start}; then' in deployment
    assert 'install -d -o 10001 -g 10001 -m 700 -- "$intake_spool_root"' in INSTALLER
    assert "== 10001:10001:700" in INSTALLER[INSTALLER.index("prepare_intake_spool_root() {") :]
    # The release stops only the API and the workers, never the spool.
    stops = [line for line in INSTALLER.splitlines() if " stop --timeout " in line]
    assert stops and all("intake-spool" not in line for line in stops)


def test_no_backup_copies_the_spool() -> None:
    """A held lead waits in the spool for minutes; the database is what's backed up."""
    scripts = ROOT / "infra" / "vps-foundation" / "scripts"
    restic = (scripts / "ac-restic-backup-inner").read_text(encoding="utf-8")
    # restic takes the whole tree, so the spool needs its own exclude.
    assert "backup_sources=(\n  /srv/authority-closers\n" in restic
    for pattern in ("", "/**"):
        assert f"--exclude='/srv/authority-closers/application/intake-spool{pattern}'" in restic
    drive_path = scripts / "drive_postgres_backup.py"
    if drive_path.exists():  # hold-only: the Drive backup stays at main in v1.1.0
        drive = drive_path.read_text(encoding="utf-8")
        assert 'ROOT = Path("/srv/authority-closers/backups")\n' in drive
        assert "intake-spool" not in drive
