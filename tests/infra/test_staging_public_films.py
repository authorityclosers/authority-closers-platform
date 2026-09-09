"""Fixed-pack deployment boundary; no Docker/VPS/database mutations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.infra.test_application_release import _bash_executable, _installer_function

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra/application"
SCRIPT = APPLICATION / "scripts/staging-public-films.py"
SOURCE_MANIFEST = ROOT / "packages/python/ac_platform/media/data/alpha_public_films_12s_v1.json"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    name = f"staging_public_films_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    application = tmp_path / "application"
    application.mkdir(mode=0o755)
    releases = application / "releases"
    releases.mkdir(mode=0o755)
    monkeypatch.setattr(module, "APPLICATION_ROOT", application)
    monkeypatch.setattr(module, "RELEASES_ROOT", releases)
    monkeypatch.setattr(module, "MEDIA_ROOT", application / "media-staging")
    # Test-owned temporary files stand in for root-owned deployment files; the
    # deployed CLI has no UID/root/path override. Linux still checks real modes.
    monkeypatch.setattr(module, "ROOT_UID", getattr(os, "getuid", lambda: 0)())
    monkeypatch.setattr(module, "ROOT_GID", getattr(os, "getgid", lambda: 0)())
    original_metadata = module._trusted_metadata
    ancestors = {(path.stat().st_dev, path.stat().st_ino) for path in application.parents}

    def test_metadata(info, *, read_only=False):
        if os.name == "nt" or (info.st_dev, info.st_ino) in ancestors:
            return  # POSIX ownership/modes are separately tested, not claimed on NTFS.
        original_metadata(info, read_only=read_only)

    monkeypatch.setattr(module, "_trusted_metadata", test_metadata)

    def release(letter="a", enabled=False, policy=True):
        path = releases / (letter * 40)
        path.mkdir(mode=0o755)
        (path / "RELEASE-COMMIT").write_bytes((letter * 40 + "\n").encode("ascii"))
        for relative in (
            "data/alpha_public_films_12s_v1.json",
            "compose.staging-public-films.yaml",
        ):
            destination = path / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            destination.write_bytes((APPLICATION / relative).read_bytes())
        if policy:
            destination = path / module.POLICY_RELATIVE
            destination.parent.mkdir(mode=0o755)
            value = json.loads((APPLICATION / module.POLICY_RELATIVE).read_bytes())
            value["enabled"] = enabled
            destination.write_text(json.dumps(value), encoding="utf-8")
        for destination in path.rglob("*"):
            if destination.is_file():
                destination.chmod(0o644)
        return path

    def small_pack(release_path):
        payload = json.loads(SOURCE_MANIFEST.read_bytes())
        source = tmp_path / f"source-{uuid4().hex}"
        source.mkdir()
        total = 0
        for clip in payload["clips"]:
            for item in clip["objects"]:
                body = ("isolated test object: " + item["path"]).encode()
                destination = source / item["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(body)
                item["content_length"] = len(body)
                item["sha256"] = hashlib.sha256(body).hexdigest()
                total += len(body)
        raw = json.dumps(payload).encode()
        digest = hashlib.sha256(raw).hexdigest()
        monkeypatch.setattr(module, "MANIFEST_SHA256", digest)
        monkeypatch.setattr(module, "PACK_BYTES", total)
        (release_path / module.MANIFEST_RELATIVE).write_bytes(raw)
        policy_file = release_path / module.POLICY_RELATIVE
        policy = json.loads(policy_file.read_bytes())
        policy["manifest_sha256"] = digest
        policy_file.write_text(json.dumps(policy), encoding="utf-8")
        return source, module.load_manifest(release_path)

    return SimpleNamespace(
        module=module,
        release=release,
        small_pack=small_pack,
        original_metadata=original_metadata,
        root=application,
    )


def test_thin_archive_manifest_is_identical_to_the_api_and_compiled_pin(harness):
    module = harness.module
    raw = (APPLICATION / module.MANIFEST_RELATIVE).read_bytes()
    assert raw == SOURCE_MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == module.MANIFEST_SHA256
    assert json.loads((APPLICATION / module.POLICY_RELATIVE).read_bytes())["enabled"] is False
    files = module.load_manifest(harness.release())
    assert len(files) == 30 and sum(item.length for item in files) == 54_274_209


def test_off_and_pre_capability_releases_need_no_installed_pack(harness):
    module = harness.module
    disabled = harness.release(enabled=False)
    old = harness.release("b", policy=False)
    for release in (disabled, old):
        assert not module.load_policy(release, "staging")
        assert module.compose_file(release, "staging") == ""
        module.preflight(release, "staging")
    assert not module.MEDIA_ROOT.exists()


def test_production_ignores_staging_policy_and_refuses_pack_install_before_io(harness, monkeypatch):
    module = harness.module
    release = harness.release(enabled=True)

    def unexpected(*args, **kwargs):
        pytest.fail("production touched staging artifact paths")

    monkeypatch.setattr(module, "_release_root", unexpected)
    assert module.compose_file(release, "production") == ""
    module.preflight(release, "production")
    with pytest.raises(module.PackError, match="staging-only"):
        module.install_pack(release, "production", Path("/missing"))


def test_enabled_release_requires_exact_existing_pack_before_composition(harness):
    module = harness.module
    release = harness.release(enabled=True)
    assert module.compose_file(release, "staging") == str(release / module.OVERRIDE_RELATIVE)
    with pytest.raises((module.PackError, FileNotFoundError)):
        module.preflight(release, "staging")


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", "true"),
        ("environment", "production"),
        ("manifest_sha256", "f" * 64),
        ("host_path", "/etc"),
        ("provider", "s3"),
        ("schema_version", "other"),
    ],
)
def test_release_policy_has_no_path_provider_or_string_activation_escape(harness, field, value):
    module = harness.module
    release = harness.release()
    policy_path = release / module.POLICY_RELATIVE
    policy = json.loads(policy_path.read_bytes())
    policy[field] = value
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(module.PackError):
        module.load_policy(release, "staging")


def test_manifest_mutation_cannot_borrow_the_pinned_digest(harness):
    module = harness.module
    release = harness.release()
    manifest = release / module.MANIFEST_RELATIVE
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(module.PackError, match="canonical API manifest"):
        module.load_manifest(release)


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.mp4",
        "/etc/passwd",
        "a/../b.ts",
        "a//b.ts",
        "C:/escape.mp4",
        "a\\b.ts",
        "a./b.ts",
    ],
)
def test_inventory_paths_cannot_introduce_host_paths(harness, relative):
    assert not harness.module._safe_relative(relative)


@pytest.mark.parametrize("change", ["missing", "extra", "length", "hash"])
def test_source_inventory_and_bytes_are_exact(harness, change):
    module = harness.module
    release = harness.release()
    source, files = harness.small_pack(release)
    target = source / files[0].path
    if change == "missing":
        target.unlink()
    elif change == "extra":
        (source / "unexpected.txt").write_text("extra", encoding="utf-8")
    elif change == "length":
        target.write_bytes(target.read_bytes() + b"extra")
    else:
        target.write_bytes(b"x" * target.stat().st_size)
    with pytest.raises(module.PackError):
        module.verify_pack(source, files, installed=False)
    assert not module.MEDIA_ROOT.exists()


@pytest.mark.parametrize("kind", ["file", "directory", "policy", "hardlink"])
def test_links_are_not_authorized_objects(harness, tmp_path, kind):
    module = harness.module
    release = harness.release()
    source, files = harness.small_pack(release)
    try:
        if kind == "policy":
            path = release / module.POLICY_RELATIVE
            original = tmp_path / "policy-copy.json"
            original.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(original)
            with pytest.raises(module.PackError):
                module.load_policy(release, "staging")
            return
        if kind == "directory":
            linked = tmp_path / "source-link"
            linked.symlink_to(source, target_is_directory=True)
            source = linked
        else:
            path = source / files[0].path
            original = tmp_path / "source-copy"
            original.write_bytes(path.read_bytes())
            path.unlink()
            if kind == "hardlink":
                os.link(original, path)
            else:
                path.symlink_to(original)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    with pytest.raises(module.PackError):
        module.verify_pack(source, files, installed=False)


@pytest.mark.parametrize(
    "mode,uid_delta,read_only",
    [
        (stat.S_IFREG | 0o644, 1, False),
        (stat.S_IFREG | 0o664, 0, False),
        (stat.S_IFREG | 0o644, 0, True),
        (stat.S_IFDIR | 0o755, 0, True),
        (stat.S_IFDIR | 0o550, 0, True),
        (stat.S_IFREG | 0o400, 0, True),
    ],
)
def test_wrong_owner_writable_or_unreadable_installed_metadata_is_rejected(
    harness,
    mode,
    uid_delta,
    read_only,
):
    info = SimpleNamespace(st_uid=harness.module.ROOT_UID + uid_delta, st_mode=mode)
    with pytest.raises(harness.module.PackError):
        harness.original_metadata(info, read_only=read_only)


@pytest.mark.skipif(os.name != "posix", reason="actual atomic install/mode proof requires POSIX")
def test_atomic_install_is_read_only_and_identical_replay_preserves_inodes(harness):
    module = harness.module
    release = harness.release()
    source, files = harness.small_pack(release)
    assert module.install_pack(release, "staging", source) == "installed"
    destination = module.MEDIA_ROOT / module.MANIFEST_SHA256
    before = {
        str(path.relative_to(destination)): (path.stat().st_ino, path.stat().st_mtime_ns)
        for path in destination.rglob("*")
    }
    assert module.install_pack(release, "staging", source) == "already_installed"
    after = {
        str(path.relative_to(destination)): (path.stat().st_ino, path.stat().st_mtime_ns)
        for path in destination.rglob("*")
    }
    assert before == after
    module.verify_pack(destination, files, installed=True)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o555
    assert all(stat.S_IMODE((destination / item.path).stat().st_mode) == 0o444 for item in files)
    assert not list(module.MEDIA_ROOT.glob(".install-*-*"))


@pytest.mark.skipif(os.name != "posix", reason="actual atomic install/mode proof requires POSIX")
def test_existing_drift_is_not_repaired_or_replaced(harness):
    module = harness.module
    release = harness.release()
    source, files = harness.small_pack(release)
    module.install_pack(release, "staging", source)
    destination = module.MEDIA_ROOT / module.MANIFEST_SHA256
    target = destination / files[0].path
    target.chmod(0o644)
    target.write_bytes(b"x" * target.stat().st_size)
    target.chmod(0o444)
    before = target.stat().st_ino
    with pytest.raises(module.PackError, match="checksum"):
        module.install_pack(release, "staging", source)
    assert target.stat().st_ino == before and target.read_bytes().startswith(b"x")


@pytest.mark.skipif(os.name != "posix", reason="actual atomic install/mode proof requires POSIX")
def test_mid_copy_failure_does_not_publish_a_partial_pack_and_cleans_stage(harness, monkeypatch):
    module = harness.module
    release = harness.release()
    source, _files = harness.small_pack(release)
    original = module._stream_verified

    def fail_copy(path, item, output=None):
        if output is not None:
            output.write(b"partial")
            raise module.PackError("injected copy failure")
        return original(path, item, output)

    monkeypatch.setattr(module, "_stream_verified", fail_copy)
    with pytest.raises(module.PackError):
        module.install_pack(release, "staging", source)
    assert not (module.MEDIA_ROOT / module.MANIFEST_SHA256).exists()
    assert not list(module.MEDIA_ROOT.glob(".install-*-*"))


def test_release_preflight_precedes_writer_stop_and_uses_both_release_identities():
    installer = (APPLICATION / "scripts/install-application-release.sh").read_text(encoding="utf-8")
    for target in ("release_dir", "previous_release"):
        assert installer.index(f'preflight "${target}" "$target_environment"') < installer.index(
            'compose_for "$writer_release" stop',
        )


@pytest.mark.parametrize("target_environment", ["staging", "production"])
def test_compose_dispatch_uses_target_release_not_latest_flag_and_scrubs_ambient_env(
    tmp_path,
    target_environment,
):
    latest, previous, old = (tmp_path / label for label in ("latest", "previous", "old"))
    for release in (latest, previous, old):
        release.mkdir()
    for release in (latest, previous):
        (release / "capabilities").mkdir()
        (release / "capabilities/staging-public-films.json").write_text(
            "test policy", encoding="utf-8"
        )
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\nset -eu\n"
        "[[ -z ${AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED+x} ]]\n"
        "[[ -z ${AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT+x} ]]\n"
        "printf '%s\\n' \"$@\"\n",
        encoding="utf-8",
        newline="\n",
    )
    docker.chmod(0o755)
    binary_path = binary.as_posix()
    if os.name == "nt":
        binary_path = "/" + binary_path[0].lower() + binary_path[2:]
    function = _installer_function("compose_for", '\n\ncompose_for "$release_dir" config --quiet')
    script = f"""set -euo pipefail
export PATH={shlex.quote(binary_path)}:"$PATH"
export AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED=true
export AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT=/untrusted
release_dir={shlex.quote(latest.as_posix())}
target_environment={shlex.quote(target_environment)}
compose_project=ac-application-{target_environment}
with_release_secrets() {{ "$@"; }}
python3() {{
  [[ "$1" == "$release_dir/scripts/staging-public-films.py" && "$2" == compose-file ]]
  [[ "$4" == staging ]]
  # Model two different immutable policies, never the ambient flags.
  if [[ "$3" == {shlex.quote(previous.as_posix())} ]]; then
    printf '%s/compose.staging-public-films.yaml\\n' "$3"
  elif [[ "$3" != "$release_dir" ]]; then exit 90; fi
}}
{function}
compose_for {shlex.quote(latest.as_posix())} config
printf 'NEXT\\n'
compose_for {shlex.quote(previous.as_posix())} config
printf 'NEXT\\n'
compose_for {shlex.quote(old.as_posix())} config
"""
    result = subprocess.run(  # noqa: S603 - executable and script are test-controlled
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    current, rollback, legacy = result.stdout.split("NEXT\n")
    assert "compose.staging-public-films.yaml" not in current + legacy
    assert ("compose.staging-public-films.yaml" in rollback) is (target_environment == "staging")
    if target_environment == "staging":
        assert str(previous.as_posix()) + "/compose.staging-public-films.yaml" in rollback


def test_effective_compose_override_mounts_only_api_and_keeps_other_services_inert(tmp_path):
    docker = shutil.which("docker.exe" if os.name == "nt" else "docker")
    if docker is None:
        pytest.skip("Docker Compose CLI is unavailable; no daemon is required for config")
    text = (APPLICATION / "compose.yaml").read_text(encoding="utf-8")
    values = {key: "test-value" for key in re.findall(r"\$\{([A-Z0-9_]+):\?", text)}
    values.update(
        {
            "AC_COMPOSE_PROJECT": "test-films",
            "AC_ENVIRONMENT": "staging",
            "AC_STATE_ROOT": "/srv/authority-closers/state/application/staging",
            "AC_API_IMAGE": "sha256:" + "a" * 64,
            "AC_LEARNER_IMAGE": "sha256:" + "b" * 64,
            "AC_ADMIN_IMAGE": "sha256:" + "c" * 64,
            "AC_COACH_IMAGE": "sha256:" + "d" * 64,
        }
    )
    result = subprocess.run(  # noqa: S603 - trusted Compose CLI; no containers are started
        [
            docker,
            "compose",
            "--file",
            str(APPLICATION / "compose.yaml"),
            "--file",
            str(APPLICATION / "compose.staging-public-films.yaml"),
            "--profile",
            "release",
            "config",
            "--format",
            "json",
        ],
        env={**os.environ, **values},
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    api = services["api"]
    mount = api["volumes"][0]
    assert len(api["volumes"]) == 1 and mount["type"] == "bind"
    assert mount["read_only"] is True

    # Older compose-go serializes false with omitempty; newer OptOut versions
    # serialize false explicitly and may omit true. Verify the source boundary
    # AND distinguish an intentionally unsafe positive control with the same
    # installed CLI. Never treat an omitted field alone as proof of safety.
    override_source = (APPLICATION / "compose.staging-public-films.yaml").read_text(
        encoding="utf-8"
    )
    assert len(re.findall(r"(?m)^\s+create_host_path: false$", override_source)) == 1
    positive_control = tmp_path / "create-host-path-enabled.yaml"
    positive_control.write_text(
        override_source.replace("create_host_path: false", "create_host_path: true"),
        encoding="utf-8",
    )
    control_args = list(result.args)
    control_args[control_args.index(str(APPLICATION / "compose.staging-public-films.yaml"))] = str(
        positive_control
    )
    control_result = subprocess.run(  # noqa: S603 - config only; unsafe control is never deployed
        control_args,
        env={**os.environ, **values},
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert control_result.returncode == 0, control_result.stderr
    control_mount = json.loads(control_result.stdout)["services"]["api"]["volumes"][0]
    omitted = object()
    disabled_value = mount.get("bind", {}).get("create_host_path", omitted)
    enabled_value = control_mount.get("bind", {}).get("create_host_path", omitted)
    assert disabled_value is False or (disabled_value is omitted and enabled_value is True)
    assert enabled_value is True or (enabled_value is omitted and disabled_value is False)
    assert mount["source"].endswith(
        "/media-staging/" + hashlib.sha256(SOURCE_MANIFEST.read_bytes()).hexdigest()
    )
    assert mount["target"] == "/run/ac-staging-public-films"
    assert api["environment"]["AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED"] == "true"
    # A third web app does not inherit fixture bytes, provider secrets or media
    # activation from the API-only override.
    assert not services["coach-web"].get("volumes")
    assert services["coach-web"]["image"] == values["AC_COACH_IMAGE"]
    assert (
        services["coach-web"]["environment"].get("AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED")
        is None
    )
    for service in (services["worker"], services["migrate"]):
        assert not service.get("volumes")
        assert service["environment"]["AC_MEDIA_STRESS_FIXTURES_ENABLED"] == "false"
        assert service["environment"]["AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED"] == "false"
    assert all(
        services[name]["environment"]["AC_MEDIA_PROVIDER_ENABLED"] == "false"
        for name in ("api", "worker", "migrate")
    )
