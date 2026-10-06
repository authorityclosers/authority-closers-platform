"""Backend repair uses fictional Git trees and simulated host commands only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys

import pytest

from tests.infra import test_refresh_dev_sales_xray_backend as contract

SCRIPT = contract.ROOT / "infra/application/scripts/refresh-dev-sales-xray-backend-only.py"
spec = importlib.util.spec_from_file_location("dev_backend_repair", SCRIPT)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tool
spec.loader.exec_module(tool)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    # The fixture patches the same byte-identical helper to simulate host identity.
    monkeypatch.setattr(tool, "helper", contract.refresh)
    return contract.tree.__wrapped__(tmp_path, monkeypatch)


def assert_ui_preserved(paths, fake):
    assert not paths.studio_lock.exists()
    assert not any(args[0] == "runuser" for args, _ in fake.calls)
    assert not any(str(paths.studio) in args for args, _ in fake.calls)
    assert not any(item.endswith("/ac_smoke.py") for args, _ in fake.calls for item in args)
    assert (paths.studio / "owner-draft.txt").read_bytes() == b"fictional owner draft\n"


def draft(paths):
    (paths.studio / "owner-draft.txt").write_bytes(b"fictional owner draft\n")


def test_pin_matches_reseal_and_changed_helper_is_not_executed(tmp_path, monkeypatch):
    assert hashlib.sha256(contract.SCRIPT.read_bytes()).hexdigest() == tool.HELPER_SHA256
    reseal = contract.ROOT / "infra/application/scripts/reseal-dev-sales-xray-approval.py"
    assert tool.HELPER_SHA256 in reseal.read_text()
    assert tool.helper.studio_step is not None and tool.helper.smoke is not None
    marker = tmp_path / "executed"
    (tmp_path / contract.SCRIPT.name).write_text(f"open({str(marker)!r}, 'w').close()\n")
    monkeypatch.setattr(tool, "__file__", str(tmp_path / SCRIPT.name))
    with pytest.raises(RuntimeError, match="reviewed_helper_digest_mismatch"):
        tool.load_helper()
    assert not marker.exists()


def test_backend_install_and_noop_leave_owner_ui_intact(tree, capsys):
    paths, sha, _, _ = tree
    draft(paths)
    fake = contract.FakeCommands(sha)
    fake.studio_conflict = True
    result = tool.refresh(paths, fake, uid=0)
    assert result["studio"] == "preserved" and result["smoke"] == "skipped"
    assert result["target"] == sha and result["health"]["ok"]
    assert (paths.backend / ".ac-release-id").read_text().strip() == sha
    assert contract.restarts(fake) == list(contract.UNIT_ORDER)
    migration = contract.sandbox_steps(fake)[0]
    assert migration[-2:] == ["upgrade", "head"]
    assert "User=10001" in migration and "MemoryMax=768M" in migration
    assert_ui_preserved(paths, fake)
    receipt = capsys.readouterr().out
    assert json.loads(receipt) == result
    assert "secret" not in receipt and "postgresql://" not in receipt
    fake.calls.clear()
    result = tool.refresh(paths, fake, uid=0)
    assert result["noop"] and result["migrated"] == "no" and result["restarted"] == []
    assert not contract.sandbox_steps(fake)
    assert_ui_preserved(paths, fake)


@pytest.mark.parametrize("guard", ["root", "identity", "native", "migration", "host"])
def test_admission_failure_precedes_any_host_mutation(tree, guard, monkeypatch):
    paths, sha, _, _ = tree
    draft(paths)
    fake = contract.FakeCommands(sha)
    uid, code = 0, "root_required"
    if guard == "root":
        uid = 10001
    elif guard == "identity":
        contract.identity(monkeypatch, missing=True)
        code = "runtime_identity_missing"
    elif guard == "native":
        paths.native_units.write_text('{"environment":"production"}')
        code = "dev_native_inputs_changed"
    elif guard == "migration":
        paths.migrator_env.chmod(0o644)
        code = "migrator_env_invalid"
    elif guard == "host":
        paths.development.joinpath("api.env").write_text("AC_INTERNAL_API_HOST=bad/host\n")
        code = "probe_host_invalid"
    with pytest.raises(tool.helper.RefreshError, match=code):
        tool.refresh(paths, fake, uid=uid)
    assert not paths.backend.exists()
    assert not paths.api_dropin.exists() and not paths.worker_dropin.exists()
    assert not any(args[0] in ("uv", "systemd-run", "systemctl") for args, _ in fake.calls)
    assert_ui_preserved(paths, fake)


@pytest.mark.parametrize("phase", ["dependency", "migration", "restart", "health"])
def test_first_install_failure_rolls_back_without_touching_ui(tree, capsys, monkeypatch, phase):
    paths, sha, _, _ = tree
    draft(paths)
    fake = contract.FakeCommands(sha)
    code = "dependency_sync_failed"
    if phase == "dependency":
        fake.fail.add("uv")
    elif phase == "migration":
        fake.fail.add("migration")
        code = "migration_failed"
    elif phase == "restart":
        fake.fail_api_restart = True
        fake.restart_status = 217
        code = "api_restart_failed"
    elif phase == "health":
        fake.api_hosts = {"wrong.invalid"}
        monkeypatch.setattr(tool.helper, "HEALTH_WAIT_SECONDS", 0)
        code = "health_release_mismatch"
    with pytest.raises(tool.helper.RefreshError, match=code):
        tool.refresh(paths, fake, uid=0)
    receipt = capsys.readouterr().out
    result = json.loads(receipt)
    assert result["rollback"]["ok"] and result["previous"] is None
    assert result["migrated"] == ("yes" if phase in ("restart", "health") else "no")
    assert fake.units == dict.fromkeys(fake.units, "inactive")
    assert not paths.backend.exists()
    assert not paths.api_dropin.exists() and not paths.worker_dropin.exists()
    assert_ui_preserved(paths, fake)
    assert "secret" not in receipt and "postgresql://" not in receipt


def test_existing_backend_and_manifest_are_restored_on_failure(tree, capsys):
    paths, sha, work, release = tree
    draft(paths)
    fake = contract.FakeCommands(sha)
    tool.refresh(paths, fake, uid=0)
    capsys.readouterr()
    saved = {
        p: p.read_bytes()
        for p in (
            paths.api_dropin,
            paths.worker_dropin,
            paths.development / "service.json",
            paths.backend / ".ac-release-id",
        )
    }
    (work / "later.txt").write_text("fictional next release\n")
    contract.git("add", ".", cwd=work)
    contract.git("commit", "-m", "next", cwd=work)
    target = contract.git("rev-parse", "HEAD", cwd=work)
    contract.git("push", "origin", "HEAD", cwd=work)
    release(target)
    paths.application.joinpath("current-staging").unlink()
    paths.application.joinpath("current-staging").symlink_to(release(target))
    fake.fail_api_restart = True
    with pytest.raises(tool.helper.RefreshError, match="api_restart_failed"):
        tool.refresh(paths, fake, uid=0)
    result = json.loads(capsys.readouterr().out)
    assert result["previous"] == sha and result["rollback"]["ok"]
    assert contract.git("rev-parse", "HEAD", cwd=paths.backend) == sha
    assert all(p.read_bytes() == content for p, content in saved.items())
    assert all(state == "active" for state in fake.units.values())
    assert_ui_preserved(paths, fake)


def test_dirty_backend_refuses_before_mutation(tree, capsys):
    paths, sha, work, release = tree
    fake = contract.FakeCommands(sha)
    tool.refresh(paths, fake, uid=0)
    capsys.readouterr()
    (work / "tracked.txt").write_text("next\n")
    contract.git("add", ".", cwd=work)
    contract.git("commit", "-m", "next", cwd=work)
    target = contract.git("rev-parse", "HEAD", cwd=work)
    contract.git("push", "origin", "HEAD", cwd=work)
    paths.application.joinpath("current-staging").unlink()
    paths.application.joinpath("current-staging").symlink_to(release(target))
    tracked = paths.backend / "scripts/ops/ac_smoke.py"
    tracked.write_text("fictional dirty backend\n")
    fake.calls.clear()
    with pytest.raises(tool.helper.RefreshError, match="backend_dirty"):
        tool.refresh(paths, fake, uid=0)
    assert tracked.read_text() == "fictional dirty backend\n"
    assert not contract.restarts(fake) and not contract.sandbox_steps(fake)
