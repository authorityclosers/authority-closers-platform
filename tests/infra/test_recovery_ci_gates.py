"""Ensure required recovery regressions have usable, isolated CI prerequisites."""

from __future__ import annotations

import shlex
from pathlib import Path

import yaml
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
HISTORICAL_CONTROLLER = (
    "35c658bd028b4fc3a7c048ab72dae700cd7682d6:infra/application/scripts/restore-drill.py"
)


def _validation_job(name: str) -> dict:
    workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    job = workflow["jobs"]["validate"]
    assert "if" not in job and not job.get("continue-on-error", False)
    return job


def _required_step(job: dict, name: str) -> dict:
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1, f"Missing or duplicated required step: {name}"
    step = matches[0]
    assert "if" not in step and not step.get("continue-on-error", False)
    return step


def test_media_and_worker_proofs_use_a_separate_matching_postgres_service() -> None:
    job = _validation_job("application.yml")
    canonical = make_url(job["env"]["AC_DATABASE_URL"])
    migrator = make_url(job["env"]["AC_DATABASE_MIGRATOR_URL"])
    media = make_url(job["env"]["AC_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST_URL"])
    service = job["services"]["postgres-recovery-tests"]
    assert (canonical.port, canonical.database, canonical.username) == (
        5432,
        "ac_platform",
        "ac_runtime",
    )
    assert (migrator.port, migrator.database, migrator.username) == (
        5432,
        "ac_platform",
        "ac_migrator",
    )
    assert (media.host, media.port, media.database, media.username, media.query) == (
        "127.0.0.1",
        55432,
        "ac_local_sandbox",
        "ac_owner",
        {},
    )
    assert service["ports"] == ["55432:5432"]
    assert media.database == service["env"]["POSTGRES_DB"]
    assert media.username == service["env"]["POSTGRES_USER"]
    assert media.password == service["env"]["POSTGRES_PASSWORD"]
    assert service["image"] == job["services"]["postgres"]["image"]
    assert "@sha256:" in service["image"]
    assert "pg_isready -U ac_owner -d ac_local_sandbox" in service["options"]

    step = _required_step(job, "Prove worker isolation and operations bootstrap")
    assert step["env"]["AC_REQUIRE_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST"] == "1"
    assert step["env"]["AC_REQUIRE_OPERATIONS_BOOTSTRAP_POSTGRES_TEST"] == "1"
    assert make_url(step["env"]["AC_OPERATIONS_BOOTSTRAP_POSTGRES_TEST_URL"]) == media
    assert shlex.split(step["run"]) == [
        "uv",
        "run",
        "pytest",
        "tests/integration/test_job_kind_isolation_postgresql.py",
        "tests/integration/test_studio_video_worker_fence_postgresql.py",
        "tests/integration/test_operations_bootstrap_postgresql.py",
    ]


def test_populated_migration_is_required_on_its_own_created_database() -> None:
    job = _validation_job("application.yml")
    step = _required_step(job, "Prove the populated prior-head migration regression")
    assert step["env"]["AC_REQUIRE_MIGRATION_REHEARSAL_POSTGRES_TEST"] == "1"
    url = make_url(step["env"]["AC_MIGRATION_REHEARSAL_POSTGRES_TEST_URL"])
    assert (url.host, url.port, url.database, url.query) == (
        "127.0.0.1",
        55432,
        "ac_migration_rehearsal_ci",
        {},
    )
    service = job["services"]["postgres-recovery-tests"]
    assert url.username == service["env"]["POSTGRES_USER"]
    assert url.password == service["env"]["POSTGRES_PASSWORD"]
    assert url.database != service["env"]["POSTGRES_DB"]
    assert shlex.split(step["run"]) == [
        "uv",
        "run",
        "pytest",
        "tests/integration/test_migration_rehearsal_postgresql.py",
    ]
    create = _required_step(job, "Create the dedicated migration regression database")
    assert shlex.split(create["run"]) == [
        "createdb",
        "--host",
        url.host,
        "--port",
        str(url.port),
        "--username",
        url.username,
        url.database,
    ]
    assert create["env"]["PGPASSWORD"] == url.password
    assert job["steps"].index(create) < job["steps"].index(step)
    assert job["env"]["AC_EXTERNAL_SIDE_EFFECTS_HOLD"] == "true"


def test_historical_and_codec_proofs_cannot_silently_lose_prerequisites() -> None:
    for workflow in ("application.yml", "control-plane.yml"):
        job = _validation_job(workflow)
        checkout = job["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert checkout["with"]["fetch-depth"] == 0
        assert checkout["with"]["persist-credentials"] is False
        history = _required_step(job, "Require the exact historical backup controller")
        assert shlex.split(history["run"]) == [
            "git",
            "cat-file",
            "-e",
            HISTORICAL_CONTROLLER,
        ]
    application = _validation_job("application.yml")
    control = _validation_job("control-plane.yml")
    assert control["env"]["AC_REQUIRE_HISTORICAL_BACKUP_CONTROLLER_TEST"] == "1"
    root_runner = (ROOT / "tests" / "infra" / "run.sh").read_text(encoding="utf-8")
    assert 'local require_history="${AC_REQUIRE_HISTORICAL_BACKUP_CONTROLLER_TEST:-0}"' in (
        root_runner
    )
    assert root_runner.count('AC_REQUIRE_HISTORICAL_BACKUP_CONTROLLER_TEST="$require_history"') == 2
    codec = _required_step(application, "Require codec and filesystem tools for media regressions")
    assert [shlex.split(line) for line in codec["run"].splitlines()] == [
        ["set", "-euo", "pipefail"],
        ["sudo", "apt-get", "update"],
        [
            "sudo",
            "apt-get",
            "install",
            "--yes",
            "--no-install-recommends",
            "ffmpeg",
            "e2fsprogs",
            "util-linux",
        ],
        ["command", "-v", "ffmpeg"],
        ["command", "-v", "ffprobe"],
        ["ffmpeg", "-version"],
        ["ffprobe", "-version"],
    ]
    validate = _required_step(application, "Validate application")
    assert application["steps"].index(codec) < application["steps"].index(validate)


def test_sales_xray_static_preview_is_built_before_application_validation() -> None:
    job = _validation_job("application.yml")
    preview = _required_step(job, "PRE-VALIDATION: Build Sales Xray static preview")
    assert preview["env"] == {
        "AC_SALES_XRAY_STATIC_PREVIEW": "1",
        "NEXT_TELEMETRY_DISABLED": "1",
    }
    assert shlex.split(preview["run"]) == [
        "pnpm",
        "--filter",
        "@ac/sales-xray-web",
        "build",
    ]
    install = _required_step(job, "Install locked dependencies")
    validate = _required_step(job, "Validate application")
    assert job["steps"].index(install) < job["steps"].index(preview) < job["steps"].index(validate)
