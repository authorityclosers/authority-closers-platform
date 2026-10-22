"""Execute installer recovery functions against a fictional host and database.

No Docker, services, credentials, live paths or external requests are used.
The real shell control flow, private files, checksums and audit writes run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = (ROOT / "infra/application/scripts/install-application-release.sh").read_text()


def function(name: str) -> str:
    return name + "() {" + INSTALLER.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


def run_failure(tmp_path: Path, failure: str, *, schema: bool = False, exposed=False):
    previous, candidate = tmp_path / "old", tmp_path / "new"
    for release in (previous, candidate):
        (release / "scripts").mkdir(parents=True)
        (release / "scripts/migrate-pg-stat-statements.sh").write_text("fixture extension step")
    (tmp_path / "backups").mkdir()
    (tmp_path / "deployments/fictional").mkdir(parents=True)
    (tmp_path / "deployments/fictional/prior.env").write_text("AC_STATUS=COMMITTED\n")
    (tmp_path / "pg-state").write_text("old")
    (tmp_path / "accepted-write").write_text("accepted fictional row")
    (tmp_path / "current").symlink_to(candidate if exposed else previous)
    (tmp_path / "edge").symlink_to(candidate if exposed else previous)
    names = (
        "set_database_writer_access",
        "take_pre_restart_snapshot",
        "prepare_postgres_release",
        "rollback_release",
        "contain_forward_recovery",
        "record_forward_recovery_required",
        "finish",
    )
    script = "set -euo pipefail\n" + "\n".join(function(name) for name in names)
    script += r"""
cd "$fixture"
events="$fixture/events"
release_dir="$fixture/new" previous_release="$fixture/old"
application_root="$fixture" target_environment=fictional
release_id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
backup_file="$fixture/backups/fictional.dump"
: > "$backup_file"
mutation_started=1 database_mutation_started=0 postgres_restart_started=0 schema_mutation_started=0
backup_ready=0 backup_sha256='' snapshot_record_file='' release_committed=0 write_exposure_started=0
current_tmp='' evidence_tmp='' attempt_tmp='' current_switch_armed=0
current_link="$fixture/current" edge_route_link="$fixture/edge"
edge_hold_source=hold api_host=fictional.invalid
forward_recovery_ingress_held=false forward_recovery_services_stopped=false
forward_recovery_writers_fenced=false
event() { printf '%s\n' "$*" >> "$events"; }
# Ownership changes require root on the real host. All file content, modes,
# digest, atomic moves and append-only receipt behavior run on actual files.
chown() { event ownership; }
install() { command install -d -m 0750 "${@: -1}"; }
sync() {
  if [[ "$failure" == receipt-sync && "${*: -1}" == */deployments/fictional ]]; then
    return 80
  fi
  command sync "$@"
}
mv() {
  if [[ "$failure" == receipt && "$*" == *-pre-restart-* ]]; then return 81; fi
  command mv "$@"
}
cleanup_stages() { :; }
stop_application_services_with_hosted_drain() { event "stop:${1##*/}"; }
restore_current_link() { event restore-link; }
restore_edge_route() { event restore-route; }
activate_edge_route() { event "route:$1"; }
check_route() { :; }
compose_for() {
  local release="${1##*/}"; shift
  if [[ "$1" == up ]]; then
    event "up:$release:${*: -1}"
    if [[ "$release" == new && "$failure" == startup* ]]; then
      printf stopped > pg-state; return 71
    fi
    if [[ "$release" == old && "$failure" == startup-recovery ]]; then return 72; fi
    if [[ "${*: -1}" == postgres ]]; then
      # The verified private snapshot and its immutable receipt precede restart.
      if [[ "$release" == new ]]; then
        [[ "$backup_ready" == 1 && -s "$snapshot_record_file" ]] || return 73
        [[ "$(stat -c %a "$backup_file")" == 600 ]] || return 74
        [[ "$(stat -c %a "$snapshot_record_file")" == 600 ]] || return 75
      fi
      printf '%s' "$release" > pg-state
    fi
    return 0
  fi
  [[ "$1" == exec ]] || return 76
  [[ "$(cat pg-state)" != stopped ]] || { event sql-against-stopped-pg; return 77; }
  if [[ "$*" == *pg_dump* ]]; then
    event "dump:$release"
    [[ "$failure" != dump ]] || return 78
    printf PGDMP-fictional
  elif [[ "$*" == *pg_restore\ --list* ]]; then
    event "verify:$release"
    cat >/dev/null
    [[ "$failure" != verify ]] || return 79
  elif [[ "$*" == *pg_restore* ]]; then
    event "restore:$release"; cat >/dev/null
    printf lost > accepted-write
  elif [[ "$*" == *REVOKE\ CONNECT* ]]; then
    if [[ "${*: -1}" == runtime ]]; then event "reopen:$release";
    else event "fence:$release"; fi
  elif [[ "$*" == *GRANT\ CONNECT* ]]; then
    event "reopen:$release"
  else
    event "extension:$release"; cat >/dev/null
  fi
}
trap finish EXIT
"""
    # Execute the actual deployment sequence, rather than a copied implementation.
    deployment = INSTALLER.split("trap finish EXIT\n", 1)[1]
    prepare = deployment.split("prepare_postgres_release", 1)[0]
    script += prepare
    script += "prepare_postgres_release\n"
    if schema or exposed:
        script += "schema_mutation_started=1\n"
    if failure == "corrupt":
        script += 'printf corrupted > "$backup_file"\n'
    if exposed:
        script += "write_exposure_started=1\n"
    script += "exit 91\n"
    result = subprocess.run(  # noqa: S603 - actual shell functions, fictional host only
        ["/bin/bash", "-c", script],
        env={**os.environ, "fixture": str(tmp_path), "failure": failure},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    events = (tmp_path / "events").read_text().splitlines()
    assert result.returncode != 0
    assert "sql-against-stopped-pg" not in events
    assert (tmp_path / "deployments/fictional/prior.env").read_text() == "AC_STATUS=COMMITTED\n"
    return result, events


@pytest.mark.parametrize("failure", ["dump", "verify", "receipt"])
def test_snapshot_failure_never_restarts_postgres(tmp_path, failure):
    _, events = run_failure(tmp_path, failure)
    assert not any(e.startswith("up:new") for e in events)
    assert not any(e.startswith("restore:") for e in events)
    assert "reopen:old" in events
    assert not (tmp_path / "backups/fictional.dump").exists()
    assert not list((tmp_path / "deployments/fictional").glob("*-pre-restart-*.env"))


def test_failed_receipt_directory_sync_keeps_published_snapshot_without_restart(tmp_path):
    _, events = run_failure(tmp_path, "receipt-sync")
    assert not any(e.startswith("up:new") for e in events)
    assert (tmp_path / "backups/fictional.dump").read_text() == "PGDMP-fictional"
    assert len(list((tmp_path / "deployments/fictional").glob("*-pre-restart-*.env"))) == 1


def test_failed_candidate_start_restores_old_postgres_before_database_operations(tmp_path):
    result, events = run_failure(tmp_path, "startup")
    start = events.index("up:new:postgres")
    recovered = events.index("up:old:postgres")
    assert start < recovered < events.index("fence:old", recovered)
    assert recovered < events.index("reopen:old")
    assert not any(e.startswith("restore:") for e in events)
    assert (tmp_path / "backups/fictional.dump").read_text() == "PGDMP-fictional"
    assert "matching edge route restored" in result.stderr
    receipts = list((tmp_path / "deployments/fictional").glob("*-pre-restart-*.env"))
    assert len(receipts) == 1
    assert "AC_BACKUP_SHA256=" in receipts[0].read_text()


def test_old_postgres_recovery_failure_stays_closed_without_sql_or_reopening(tmp_path):
    result, events = run_failure(tmp_path, "startup-recovery")
    recovered = events.index("up:old:postgres")
    assert not any(e.startswith(("fence:", "reopen:", "restore:")) for e in events[recovered:])
    assert "Automatic application rollback was incomplete" in result.stderr


def test_pre_exposure_schema_failure_restores_verified_snapshot_on_old_postgres(tmp_path):
    _, events = run_failure(tmp_path, "schema", schema=True)
    recovered = events.index("up:old:postgres")
    assert recovered < events.index("fence:old", recovered) < events.index("restore:old")
    assert events.index("restore:old") < events.index("reopen:old")


def test_corrupt_snapshot_refuses_restore_and_runtime_access(tmp_path):
    result, events = run_failure(tmp_path, "corrupt", schema=True)
    assert "Recovery snapshot checksum changed" in result.stderr
    assert not any(e.startswith(("restore:", "reopen:")) for e in events)


def test_post_write_failure_preserves_row_and_append_only_forward_recovery(tmp_path):
    _, events = run_failure(tmp_path, "late", exposed=True)
    assert (tmp_path / "accepted-write").read_text() == "accepted fictional row"
    assert not any(e.startswith(("up:old:", "restore:", "reopen:")) for e in events)
    assert "route:hold" in events
    records = list((tmp_path / "deployments/fictional").glob("*-forward-recovery-required-*.env"))
    assert len(records) == 1
    assert "AC_RECOVERY_ACTION=REAPPLY_EXACT_RELEASE" in records[0].read_text()
    assert (tmp_path / "current").resolve() == tmp_path / "new"


def test_privileged_draft_is_not_activated_before_allocated_migration_and_review():
    deployment = INSTALLER.split("trap finish EXIT\n", 1)[1]
    assert deployment.index("prepare_postgres_release") < deployment.index(
        "schema_mutation_started=1"
    )
    assert deployment.index("schema_mutation_started=1") < deployment.index(
        "set_database_writer_access migrator"
    )
    assert "migrate-pg-stat-statements.sh" not in INSTALLER
