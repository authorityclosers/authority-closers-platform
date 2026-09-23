"""Ensure required recovery regressions have usable, isolated CI prerequisites."""

from __future__ import annotations

import re
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
    job_id = "validate-python-gates" if name == "application.yml" else "validate"
    job = workflow["jobs"][job_id]
    assert "if" not in job and not job.get("continue-on-error", False)
    return job


def _workflow_job(name: str, job_id: str) -> dict:
    workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return workflow["jobs"][job_id]


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
    browser = _required_step(
        application, "Prove registration consent and server-rendered readiness"
    )
    assert application["steps"].index(codec) < application["steps"].index(browser)


def test_sales_xray_static_preview_is_built_before_application_validation() -> None:
    frontend = _workflow_job("application.yml", "validate-frontend")
    preview = _required_step(frontend, "PRE-VALIDATION: Build Sales Xray static preview")
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
    install = _required_step(frontend, "Install locked Node dependencies")
    assert frontend["steps"].index(install) < frontend["steps"].index(preview)

    python_tests = _workflow_job("application.yml", "validate-python-tests")
    shard_preview = _required_step(python_tests, "PRE-VALIDATION: Build Sales Xray static preview")
    shard_install = _required_step(python_tests, "Install locked dependencies")
    assert python_tests["steps"].index(shard_install) < python_tests["steps"].index(shard_preview)


def test_sales_xray_acquisition_browser_gate_is_required_and_aggregated() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "application.yml").read_text(encoding="utf-8"))
    gate_id = "validate-sales-xray-acquisition-browser"
    gate = workflow["jobs"][gate_id]
    assert "if" not in gate and not gate.get("continue-on-error", False)
    service = gate["services"]["postgres"]
    database = make_url(gate["env"]["AC_CONVERSATION_POSTGRES_TEST_URL"])
    assert (database.host, database.port, database.database, database.username) == (
        "127.0.0.1",
        5432,
        "ac_sales_xray_browser",
        "ac_owner",
    )
    assert service["env"] == {
        "POSTGRES_DB": "ac_sales_xray_browser",
        "POSTGRES_USER": "ac_owner",
        "POSTGRES_PASSWORD": "local-owner-only",
    }
    assert service["ports"] == ["5432:5432"]
    assert service["image"].startswith("postgres@sha256:")
    assert "pg_isready -U ac_owner -d ac_sales_xray_browser" in service["options"]
    assert gate["env"]["AC_TEST_DATABASE_URL"] == gate["env"]["AC_CONVERSATION_POSTGRES_TEST_URL"]
    assert gate["env"]["AC_EXTERNAL_SIDE_EFFECTS_HOLD"] == "true"

    names = [step.get("name") for step in gate["steps"]]
    install = _required_step(gate, "Install locked browser-gate dependencies")
    codecs = _required_step(gate, "Install FFmpeg prerequisites for acquisition browser")
    browser = _required_step(gate, "Install locked acquisition browser")
    native = _required_step(gate, "Build verified AudioAtlas for acquisition browser")
    build = _required_step(gate, "Build Sales Xray production standalone")
    required = _required_step(gate, "Require Sales Xray acquisition browser journey")
    receipt = next(
        step
        for step in gate["steps"]
        if step.get("name") == "Upload sanitized Sales Xray acquisition receipt"
    )
    assert receipt["if"] == "always()"
    assert receipt["uses"].startswith("actions/upload-artifact@")
    assert receipt["with"]["if-no-files-found"] == "error"
    assert "sales-xray-acquisition-browser-receipt.json" in receipt["with"]["path"]
    assert "proof.json" in receipt["with"]["path"]
    assert names.index(install["name"]) < names.index(codecs["name"]) < names.index(browser["name"])
    assert [shlex.split(line) for line in codecs["run"].splitlines()] == [
        ["set", "-euo", "pipefail"],
        ["sudo", "apt-get", "update"],
        [
            "sudo",
            "apt-get",
            "install",
            "--yes",
            "--no-install-recommends",
            "ffmpeg",
        ],
        ["command", "-v", "ffmpeg"],
        ["command", "-v", "ffprobe"],
        ["ffmpeg", "-version"],
        ["ffprobe", "-version"],
    ]
    assert names.index(browser["name"]) < names.index(native["name"])
    assert names.index(native["name"]) < names.index(build["name"])
    assert [shlex.split(line) for line in native["run"].splitlines()] == [
        ["set", "-euo", "pipefail"],
        ["command", "-v", "g++"],
        ["g++", "--version"],
        [
            "uv",
            "run",
            "--frozen",
            "python",
            "-c",
            "from ac_platform.conversation_intelligence.signals import build_native, "
            "_native_executable; built = build_native(); "
            "assert _native_executable(None) == built.resolve()",
        ],
    ]
    assert names.index(build["name"]) < names.index(required["name"])
    assert shlex.split(build["run"]) == ["pnpm", "--filter", "@ac/sales-xray-web", "build"]
    assert build["env"] == {
        "AC_CONVERSATION_API_ORIGIN": "http://127.0.0.1:18116",
        "NEXT_TELEMETRY_DISABLED": "1",
    }
    assert "AC_SALES_XRAY_STATIC_PREVIEW" not in build.get("env", {})
    assert shlex.split(required["run"]) == [
        "uv",
        "run",
        "--frozen",
        "python",
        "scripts/ci/verify_sales_xray_acquisition_browser.py",
        "--evidence-dir",
        "${{ runner.temp }}/sales-xray-acquisition-browser-${{ github.sha }}",
    ]
    assert required["timeout-minutes"] == 20
    wrapper = (ROOT / "scripts/ci/verify_sales_xray_acquisition_browser.py").read_text("utf-8")
    assert '"--basetemp"' in wrapper
    browser_test = (ROOT / "tests/e2e/test_sales_xray_acquisition_browser.py").read_text("utf-8")
    assert "source upload failed:" in browser_test
    assert '" ".join(detail.split())[:240]' in browser_test
    assert "test_compiled_account_required_upload_profile_otp_report_relogin_and_deletion" in (
        wrapper
    )
    for assertion in (
        "pre-auth requests contain no source upload or processing plan",
        "email OTP delivered through local outbox and verified",
        "required account name and mobile profile completed",
        "originally selected audio bytes upload only after profile completion",
        "uploaded source hash matches originally selected audio bytes",
        "acquisition allowance settled exactly once",
        "new browser context signs in again with email OTP",
    ):
        assert assertion in wrapper
    assert browser_test.count(".set_input_files(") == 1
    assert "request.post_data_buffer" in browser_test
    assert "record_request(request)" in browser_test
    assert "external_mutating_requests == []" in browser_test
    assert "actual password login and two-workspace chooser" not in wrapper

    validation = workflow["jobs"]["validate"]
    assert gate_id in validation["needs"]
    aggregate = next(
        step
        for step in validation["steps"]
        if step.get("name") == "Require every validation component to pass"
    )
    assert aggregate["if"] == "always()"
    assert aggregate["env"]["SALES_XRAY_ACQUISITION_BROWSER_RESULT"] == (
        "${{ needs.validate-sales-xray-acquisition-browser.result }}"
    )
    assert '"$SALES_XRAY_ACQUISITION_BROWSER_RESULT"' in aggregate["run"]


def test_sales_xray_acquisition_browser_wrapper_fails_closed_on_skips_and_sanitizes_receipt() -> (
    None
):
    wrapper = (ROOT / "scripts/ci/verify_sales_xray_acquisition_browser.py").read_text("utf-8")
    assert "The required Sales Xray acquisition browser test case is missing" in wrapper
    assert "Exactly the required Sales Xray browser case must pass without skips" in wrapper
    assert "sales-xray-acquisition-browser-receipt.json" in wrapper
    assert '"provider_network_calls": 0' in wrapper
    assert "The required browser-network receipt is missing" in wrapper


def test_conversation_native_build_is_verified_before_application_validation() -> None:
    job = _validation_job("application.yml")
    native = _required_step(job, "Build verified AudioAtlas for conversation regressions")
    assert [shlex.split(line) for line in native["run"].splitlines()] == [
        ["set", "-euo", "pipefail"],
        ["command", "-v", "g++"],
        ["g++", "--version"],
        [
            "uv",
            "run",
            "python",
            "-c",
            "from ac_platform.conversation_intelligence.signals import build_native, "
            "_native_executable; built = build_native(); "
            "assert _native_executable(None) == built.resolve()",
        ],
    ]
    install = _required_step(job, "Install locked dependencies")
    assert job["steps"].index(install) < job["steps"].index(native)


def test_python_shard_exclusions_match_every_explicit_gate_file() -> None:
    gate = _validation_job("application.yml")
    explicit_paths = sorted(
        {
            path
            for step in gate["steps"]
            for path in re.findall(r"tests/[^\s]+\.py", step.get("run", ""))
        }
    )
    exclusions = sorted(
        line.strip()
        for line in (ROOT / "scripts/ci/python-test-exclusions.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert exclusions == explicit_paths
