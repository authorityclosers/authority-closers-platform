"""Fictional AUT-2216 controls; no Docker, root, credentials or staging access."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "trusted_rehearsal", ROOT / "infra/release/trusted_rehearsal/harness.py"
)
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)
KEY = b"fictional-test-key-only-32-bytes!!"
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
CANDIDATE, BASE = "a" * 40, "b" * 40
CONFIG = {"bundle_sha256": "c" * 64, "runner_image": "ac/fixture@sha256:" + "d" * 64}


def record(**changes):
    return {
        "schema": "ac.schema_rehearsal/2",
        "candidate": CANDIDATE,
        "base": BASE,
        **CONFIG,
        "result": "PASS",
        "exported_at": (NOW - timedelta(minutes=5)).isoformat(),
        "finished_at": (NOW - timedelta(minutes=1)).isoformat(),
        "manifest_sha256": "e" * 64,
        "dump_sha256": "f" * 64,
        "alembic_revision": "20261023_0127",
        "release_id": BASE,
        **changes,
    }


def test_passing_receipt_is_exact_and_authenticated():
    value = record()
    assert h.validate_receipt(h.seal(value, KEY), KEY, CONFIG, CANDIDATE, BASE, NOW) == value


@pytest.mark.parametrize(
    "changes",
    [
        {"candidate": "2" * 40},
        {"base": "3" * 40},
        {"result": "FAIL"},
        {"bundle_sha256": "4" * 64},
        {"runner_image": "untrusted:latest"},
        {"finished_at": (NOW - timedelta(hours=2)).isoformat()},
        {"exported_at": (NOW - timedelta(hours=25)).isoformat()},
        {"exported_at": (NOW + timedelta(minutes=1)).isoformat()},
        {"finished_at": (NOW + timedelta(minutes=1)).isoformat()},
        {"finished_at": "2026-10-24T11:59:00"},
        {"manifest_sha256": "missing"},
        {"dump_sha256": "missing"},
        {"schema": "ac.schema_rehearsal/1"},
        {"extra": True},
        {"release_id": "main"},
        {"release_id": "1" * 40},
        {"alembic_revision": "head"},
    ],
)
def test_signed_but_failed_stale_or_mismatched_receipt_rejected(changes):
    with pytest.raises(h.Refusal):
        h.validate_receipt(h.seal(record(**changes), KEY), KEY, CONFIG, CANDIDATE, BASE, NOW)


def test_candidate_forgery_and_signature_replacement_rejected():
    forged = h.seal(record(), b"candidate-owned-fake-signing-key")
    with pytest.raises(h.Refusal, match="forged"):
        h.validate_receipt(forged, KEY, CONFIG, CANDIDATE, BASE, NOW)
    envelope = h.seal(record(), KEY)
    envelope["record"]["base"] = "0" * 40
    with pytest.raises(h.Refusal, match="forged"):
        h.validate_receipt(envelope, KEY, CONFIG, CANDIDATE, BASE, NOW)


def test_missing_receipt_and_untrusted_location_cannot_be_selected(monkeypatch):
    assert h.receipt_path(CANDIDATE, BASE) == h.RECEIPTS / f"{CANDIDATE}-{BASE}.json"
    for candidate in ["../fake", "HEAD", "a" * 39]:
        with pytest.raises(h.Refusal):
            h.receipt_path(candidate, BASE)
    with pytest.raises(h.Refusal):
        h.validate_receipt({}, KEY, CONFIG, CANDIDATE, BASE, NOW)
    for option in [
        "--receipts",
        "--exporter",
        "--validator",
        "--runner-image",
        "--config",
        "--retire-ci",
    ]:
        with pytest.raises(SystemExit):
            h.main(["verify", "--candidate", CANDIDATE, "--base", BASE, option, "/candidate/evil"])


def test_worker_cannot_access_credentials_network_or_host_control(monkeypatch, tmp_path):
    monkeypatch.setenv("AC_DATABASE_URL", "fictional-host-secret")
    monkeypatch.setenv("UNCLASSIFIED_SECRET", "fictional-host-secret")
    monkeypatch.setenv("DOCKER_HOST", "tcp://fictional-evil.invalid")
    source, sockets = tmp_path / "source", tmp_path / "sockets"
    argv = h.worker_argv(
        source, sockets, CONFIG["runner_image"], "fixture-worker", "upgrade", "0128"
    )
    for flag in [
        "--pull=never",
        "--network=none",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--ipc=none",
        "--pids-limit=128",
        "--memory=768m",
        "--memory-swap=768m",
    ]:
        assert flag in argv
    mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--mount"]
    assert mounts == [
        f"type=bind,src={source},dst=/candidate,readonly",
        f"type=bind,src={sockets},dst=/run/pg,readonly",
    ]
    assert not any(
        x in " ".join(argv)
        for x in ["docker.sock", "fictional-host-secret", "--privileged", "--env-file"]
    )
    assert "--offline" in " ".join(argv) and "--no-python-downloads" in " ".join(argv)
    assert argv[-3:] == ["--", "upgrade", "0128"]
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return b""

    monkeypatch.setattr(h, "command", run)
    h.docker(*argv)
    command, kwargs = calls[0]
    assert command[:3] == ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
    assert "DOCKER_HOST" not in h.ENV and "UNCLASSIFIED_SECRET" not in h.ENV
    assert kwargs["output_limit"] == 1024 * 1024


@pytest.mark.parametrize(
    "direction,revision,image",
    [
        ("upgrade", "head;id", CONFIG["runner_image"]),
        ("shell", "0128", CONFIG["runner_image"]),
        ("upgrade", "0128", "ac/fixture:latest"),
    ],
)
def test_worker_arguments_cannot_inject_commands(direction, revision, image, tmp_path):
    with pytest.raises(h.Refusal):
        h.worker_argv(tmp_path, tmp_path, image, "fixture", direction, revision)


def test_install_pin_rejects_candidate_exporter_validator_and_shadowing(tmp_path, monkeypatch):
    bundle = tmp_path / "installed"
    pins = {}
    for name in h.TRUSTED:
        p = bundle / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# reviewed fictional trusted tool\n")
        pins[name] = h.digest(p)
    (bundle / "pins.json").write_bytes(h.canonical(pins))
    config_path = tmp_path / "config.json"
    config = CONFIG | {
        "bundle": str(bundle),
        "bundle_sha256": hashlib.sha256(h.canonical(pins)).hexdigest(),
    }
    config_path.write_bytes(h.canonical(config))
    monkeypatch.setattr(h, "CONFIG", config_path)
    monkeypatch.setattr(h, "__file__", str(bundle / "infra/release/trusted_rehearsal/harness.py"))
    # Fixture tests byte-pinning separately from the production root-owner check.
    monkeypatch.setattr(h, "protected", lambda *a, **k: None)
    assert h.installation() == config
    for name in ["scripts/ops/export_migration_schema.py", "scripts/ci/migration_schema_gate.py"]:
        path = bundle / name
        original = path.read_bytes()
        path.write_text('raise RuntimeError("fictional candidate replacement")')
        with pytest.raises(h.Refusal, match="changed"):
            h.installation()
        path.write_bytes(original)
    (bundle / "scripts/__init__.py").write_text('raise RuntimeError("shadowed")')
    with pytest.raises(h.Refusal, match="unlisted"):
        h.installation()


def test_nonroot_cannot_authorize_or_rehearse(monkeypatch, capsys):
    monkeypatch.setattr(h.os, "geteuid", lambda: 12345)
    monkeypatch.setattr(h, "installation", lambda: pytest.fail("must refuse before installed read"))
    assert h.main(["verify", "--candidate", CANDIDATE, "--base", BASE]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_actual_unprivileged_path_ownership_check_refuses(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("this proof requires the unprivileged builder seat")
    file = tmp_path / "candidate-validator.py"
    file.write_text('print("PASS")')
    with pytest.raises(h.Refusal, match="replaceable"):
        h.protected(file)


def test_retained_ci_reference_keeps_live_evidence_on_alternate_merge_paths():
    # Historical retained-CI contract, deliberately separate from the concurrent
    # owner-directed workflow switch. This assertion is not current CI proof.
    workflow = (
        ROOT / "infra/release/trusted_rehearsal/required-migration-safety.yml.reference"
    ).read_text()
    for text in [
        "pull_request:",
        "push:",
        "workflow_dispatch:",
        "Require governed schema artifact identity",
        "Download only the governed schema bundle",
        "--artifact-dir",
        "--manifest-sha256",
        "expired == false",
    ]:
        assert text in workflow
    assert "--baseline-from-migrations" not in workflow


def test_trusted_exporter_selected_outside_candidate(tmp_path, monkeypatch):
    source = tmp_path / "candidate"
    sentinel = tmp_path / "candidate-ran"
    for name in ["scripts/ops/export_migration_schema.py", "scripts/ci/migration_schema_gate.py"]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'open({str(sentinel)!r}, "w").write("credential stolen")')
    bundle = tmp_path / "trusted-install"
    calls = []

    def stop_after_export(argv, **kw):
        calls.append((argv, kw))
        raise h.Refusal("fictional stop before live export")

    monkeypatch.setattr(h, "command", stop_after_export)
    with pytest.raises(h.Refusal):
        h.rehearse(
            CONFIG | {"bundle": str(bundle)},
            source,
            tmp_path / "base",
            tmp_path / "pair",
            tmp_path / "socket",
        )
    assert calls[0][0][:3] == [
        sys.executable,
        "-IB",
        str(bundle / "scripts/ops/export_migration_schema.py"),
    ]
    assert not sentinel.exists()


def test_candidate_validator_is_never_imported(tmp_path):
    # Separate isolated interpreter proves import resolution without shared test
    # module caches. Trusted code here is fictional and raises no service calls.
    bundle, candidate = tmp_path / "trusted", tmp_path / "candidate"
    for root, content in [
        (bundle, "TRUSTED = True\n"),
        (candidate, 'raise RuntimeError("candidate imported")\n'),
    ]:
        p = root / "scripts/ci/migration_schema_gate.py"
        p.parent.mkdir(parents=True)
        p.write_text(content)
    code = (
        'import importlib.util; s=importlib.util.spec_from_file_location("h", '
        f"{str(Path(h.__file__))!r}); "
        f"h=importlib.util.module_from_spec(s); s.loader.exec_module(h); "
        f"assert h.load_gate(h.Path({str(bundle)!r})).TRUSTED"
    )
    subprocess.run(  # noqa: S603 - isolated interpreter with fictional fixture modules
        [sys.executable, "-IB", "-c", code],
        cwd=candidate,
        env={"PATH": os.defpath, "PYTHONPATH": str(candidate)},
        check=True,
    )


def test_candidate_pass_text_cannot_replace_exact_database_revision(tmp_path, monkeypatch):
    from types import SimpleNamespace

    pair = tmp_path / "pair"
    pair.mkdir()
    (pair / "manifest.json").write_text("{}")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *_):
            return self

        def fetchall(self):
            return [("wrong_revision",)]

    fake = SimpleNamespace()
    fake.rehearse = lambda _pair, _hash, _baseline, _chain, revision, source: fake.migrate(
        SimpleNamespace(connect=Connection), {}, source, "upgrade", revision
    )
    calls = []
    monkeypatch.setattr(h, "command", lambda *a, **kw: b"")
    monkeypatch.setattr(h, "load_gate", lambda _: fake)
    monkeypatch.setattr(h, "migration_scope", lambda *a: ("0127", "0128", [object()]))

    def docker(*argv, **kw):
        calls.append(argv)
        return b"schema-rehearsal: PASS (forged by candidate)" if argv[0] == "run" else b""

    monkeypatch.setattr(h, "docker", docker)
    with pytest.raises(h.Refusal, match="exact requested revision"):
        h.rehearse(
            CONFIG | {"bundle": str(tmp_path)},
            tmp_path / "source",
            tmp_path / "base",
            pair,
            tmp_path / "sockets",
        )
    assert calls[0][0] == "run"
    assert calls[1][:2] == ("rm", "--force")


def test_timeout_kills_candidate_container_before_any_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace

    pair = tmp_path / "pair"
    pair.mkdir()
    (pair / "manifest.json").write_text("{}")
    fake = SimpleNamespace()
    fake.rehearse = lambda _pair, _hash, _baseline, _chain, revision, source: fake.migrate(
        object(), {}, source, "upgrade", revision
    )
    monkeypatch.setattr(h, "command", lambda *a, **kw: b"")
    monkeypatch.setattr(h, "load_gate", lambda _: fake)
    monkeypatch.setattr(h, "migration_scope", lambda *a: ("0127", "0128", [object()]))
    calls = []

    def docker(*argv, **kw):
        calls.append(argv)
        if argv[0] == "run":
            raise h.Refusal("fictional timeout")
        return b""

    monkeypatch.setattr(h, "docker", docker)
    with pytest.raises(h.Refusal, match="timeout"):
        h.rehearse(
            CONFIG | {"bundle": str(tmp_path)},
            tmp_path / "source",
            tmp_path / "base",
            pair,
            tmp_path / "sockets",
        )
    assert calls[1][:2] == ("rm", "--force")
    assert not list(tmp_path.glob("*.json"))


def test_real_container_adversarial_credential_and_socket_probe(tmp_path):
    """Root may run after approval with the reviewed offline image, never auto-pull."""
    image = os.environ.get("AC_TRUSTED_REHEARSAL_TEST_IMAGE")
    if not image:
        pytest.skip("requires approved Docker executor and pinned offline runner image")
    # A deliberately malicious module runs IN the candidate boundary and reports
    # only fictional assertions. It cannot replace the installed host harness.
    source, sockets = tmp_path / "candidate", tmp_path / "sockets"
    source.mkdir(mode=0o755)
    sockets.mkdir(mode=0o755)
    (source / "pyproject.toml").write_text(
        '[project]\nname="fictional-probe"\nversion="0.0.0"\nrequires-python=">=3.12"\n'
        "[tool.uv]\npackage=false\n"
    )
    # No dependencies or code are installed on the host. This is static lock data.
    (source / "uv.lock").write_text(
        'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n\n'
        '[[package]]\nname = "fictional-probe"\nversion = "0.0.0"\n'
        'source = { virtual = "." }\n'
    )
    (source / "alembic").mkdir()
    (source / "alembic/__init__.py").write_text("")
    (source / "alembic/__main__.py").write_text(
        "import os, pathlib, socket\n"
        "assert os.geteuid() == 65534\n"
        'assert "UNCLASSIFIED_SECRET" not in os.environ\n'
        'assert not pathlib.Path("/var/run/docker.sock").exists()\n'
        'assert not pathlib.Path("/run/ac-release/schema-rehearsal.key").exists()\n'
        'assert not pathlib.Path("/opt/ac-schema-rehearsal").exists()\n'
        'try:\n    socket.create_connection(("192.0.2.1", 443), timeout=1)\n'
        'except OSError:\n    pass\nelse:\n    raise AssertionError("network escaped")\n'
        'try:\n    pathlib.Path("/candidate/owned").write_text("attack")\n'
        'except OSError:\n    pass\nelse:\n    raise AssertionError("source mount writable")\n'
        'print("fictional-isolation-probe: PASS")\n'
    )
    name = "ac-rehearsal-probe-" + h.uuid4().hex
    try:
        output = h.docker(
            *h.worker_argv(source, sockets, image, name, "upgrade", "0128"), timeout=120
        )
        assert b"fictional-isolation-probe: PASS" in output
        assert not (source / "owned").exists()
    finally:
        h.remove_container(name)


OBJECTS = h.load_objects()


def fixture_git(repo, *args, data=None):
    # Only fictional temporary repositories. No shared checkout configuration.
    return subprocess.run(  # noqa: S603 - literal Git plumbing on fictional fixtures
        ["/usr/bin/git", "-C", str(repo), *args],
        input=data,
        env=OBJECTS.ENV
        | {
            "GIT_AUTHOR_NAME": "Fictional",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fictional",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
        check=True,
        capture_output=True,
    ).stdout


def fictional_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    fixture_git(repo, "init", "--template=")

    def revision(content, parent=None):
        entries = []
        for name, raw in sorted(content.items()):
            oid = fixture_git(repo, "hash-object", "-w", "--stdin", data=raw).strip()
            entries.append(b"100644 blob " + oid + b"\t" + name.encode() + b"\n")
        tree = fixture_git(repo, "mktree", data=b"".join(entries)).strip().decode()
        return (
            fixture_git(
                repo,
                "commit-tree",
                tree,
                *(["-p", parent] if parent else []),
                data=b"fictional commit\n",
            )
            .strip()
            .decode()
        )

    base = revision({"payload.txt": b"base\n"})
    candidate = revision(
        {
            "payload.txt": b"candidate raw $Id$\n",
            ".gitattributes": b"payload.txt filter=evil export-subst\n",
        },
        base,
    )
    return repo, base, candidate, revision


@pytest.mark.parametrize("packed", [False, True])
def test_real_git_raw_objects_ignore_smudge_and_process_filter(tmp_path, packed):
    import io

    repo, base, candidate, _ = fictional_repo(tmp_path)
    sentinel = tmp_path / "filter-executed"
    # Real smudge sentinel: positive control proves Git would execute this config.
    fixture_git(repo, "config", "filter.evil.smudge", f"touch {sentinel}; cat")
    fixture_git(repo, "config", "filter.evil.required", "true")
    (repo / ".gitattributes").write_text("payload.txt filter=evil\n")
    fixture_git(repo, "cat-file", "--filters", f"{candidate}:payload.txt")
    assert sentinel.exists()
    sentinel.unlink()
    # Process takes precedence over smudge. The failed protocol is intentional;
    # the marker proves executable local configuration would run if consulted.
    fixture_git(repo, "config", "filter.evil.process", f"touch {sentinel}; exit 1")
    with pytest.raises(subprocess.CalledProcessError):
        fixture_git(repo, "cat-file", "--filters", f"{candidate}:payload.txt")
    assert sentinel.exists()
    sentinel.unlink()
    if packed:
        # Pin fixture reachability without a branch or checkout.
        fixture_git(repo, "update-ref", "refs/fixture/candidate", candidate)
        fixture_git(repo, "repack", "-ad")
    raw = io.BytesIO()
    OBJECTS.export(repo / ".git/objects", candidate, base, raw)
    objects = OBJECTS.read_bundle(raw.getvalue())
    OBJECTS.ancestor(objects, candidate, base)
    OBJECTS.snapshot(objects, candidate, tmp_path / "snapshot")
    assert (tmp_path / "snapshot/payload.txt").read_bytes() == b"candidate raw $Id$\n"
    assert not sentinel.exists()
    # Independent interpreter exercises the exact installed reader entry point.
    result = h.command(
        [
            sys.executable,
            "-IB",
            str(Path(OBJECTS.__file__)),
            str(repo / ".git/objects"),
            candidate,
            base,
        ]
    )
    assert OBJECTS.read_bundle(result) == objects
    assert not sentinel.exists()


def test_real_git_replacement_refs_config_grafts_and_alternates_are_not_source(tmp_path):
    import io

    repo, base, candidate, revision = fictional_repo(tmp_path)
    evil = revision({"payload.txt": b"replacement must never reach snapshot"})
    fixture_git(repo, "replace", candidate, evil)
    # Normal Git follows the hostile replacement ref; the reader must not.
    unsafe_env = OBJECTS.ENV.copy()
    unsafe_env.pop("GIT_NO_REPLACE_OBJECTS")
    actual = subprocess.run(  # noqa: S603 - fictional positive control
        ["/usr/bin/git", "-C", str(repo), "show", f"{candidate}:payload.txt"],
        env=unsafe_env,
        capture_output=True,
        check=True,
    ).stdout
    assert b"replacement" in actual
    (repo / ".git/info").mkdir()
    (repo / ".git/info/grafts").write_text(candidate + "\n")
    (repo / ".git/objects/info/alternates").write_text("/fictional/never/read/objects\n")
    fixture_git(repo, "config", "extensions.partialClone", "evil")
    fixture_git(repo, "config", "remote.evil.url", "ext::touch /fictional/never/run")
    raw = io.BytesIO()
    OBJECTS.export(repo / ".git/objects", candidate, base, raw)
    objects = OBJECTS.read_bundle(raw.getvalue())
    OBJECTS.ancestor(objects, candidate, base)
    OBJECTS.snapshot(objects, candidate, tmp_path / "snapshot")
    assert (tmp_path / "snapshot/payload.txt").read_bytes() == b"candidate raw $Id$\n"
    # A missing promised object is refused; no remote helper/lazy fetch is used.
    with pytest.raises(OBJECTS.Invalid, match="missing"):
        OBJECTS.export(repo / ".git/objects", "f" * 40, base, io.BytesIO())


def test_raw_object_acquisition_refuses_declared_size_before_reading(tmp_path, monkeypatch):
    import io

    repo, base, candidate, _ = fictional_repo(tmp_path)
    monkeypatch.setattr(OBJECTS, "MAX_OBJECT", 16)
    with pytest.raises(OBJECTS.Invalid, match="acquisition"):
        OBJECTS.export(repo / ".git/objects", candidate, base, io.BytesIO())


@pytest.mark.parametrize(
    "header,body",
    [
        (b"a" * 40 + b" blob 2\n", b"xx\n"),  # forged OID
        (b"a" * 40 + b" blob 999999999\n", b""),  # limit before allocation
        (b"a" * 40 + b" blob 2\n", b"x"),  # truncation
    ],
)
def test_untrusted_reader_bytes_are_independently_refused(header, body):
    with pytest.raises(OBJECTS.Invalid):
        OBJECTS.read_bundle(header + body)


@pytest.mark.parametrize(
    "mode,name",
    [
        (b"120000", b"link"),
        (b"160000", b"submodule"),
        (b"100644", b".."),
        (b"100644", b".git"),
        (b"100644", b"x/y"),
    ],
)
def test_raw_tree_rejects_links_git_metadata_and_unsafe_paths(mode, name):
    with pytest.raises(OBJECTS.Invalid, match="unsafe"):
        list(OBJECTS.tree(mode + b" " + name + b"\0" + b"x" * 20))


def test_repeated_blob_materialization_is_bounded(tmp_path, monkeypatch):
    import io

    repo, base, _, revision = fictional_repo(tmp_path)
    candidate = revision({f"file{i}": b"x" * 500 for i in range(10)}, base)
    raw = io.BytesIO()
    OBJECTS.export(repo / ".git/objects", candidate, base, raw)
    objects = OBJECTS.read_bundle(raw.getvalue())
    monkeypatch.setattr(OBJECTS, "MAX_BYTES", 1024)
    with pytest.raises(OBJECTS.Invalid, match="materialized"):
        OBJECTS.snapshot(objects, candidate, tmp_path / "snapshot")


def test_workbench_only_enters_unprivileged_source_container(tmp_path, monkeypatch):
    repo, root = tmp_path / "unreadable-workbench", tmp_path / "private-run"
    config = CONFIG | {"bundle": str(tmp_path / "trusted-install")}
    argv = h.source_reader_argv(repo, config, "fixture", CANDIDATE, BASE)
    assert "--user=65534:65534" in argv and "--network=none" in argv
    for flag in [
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--memory=512m",
        "--log-driver=none",
        "--pids-limit=32",
    ]:
        assert flag in argv
    assert str(repo) not in argv  # only appears inside readonly mount argument
    mounts = [argv[i + 1] for i, x in enumerate(argv) if x == "--mount"]
    assert mounts == [
        f"type=bind,src={repo}/.git/objects,dst=/source-objects,readonly",
        f"type=bind,src={config['bundle']}/infra/release/trusted_rehearsal/objects.py,dst=/trusted-reader.py,readonly",
    ]
    assert argv[-5:] == ["-IB", "/trusted-reader.py", "/source-objects", CANDIDATE, BASE]
    calls = []

    def docker(*args, **kw):
        calls.append((args, kw))
        return b"forged objects" if args[0] == "run" else b""

    monkeypatch.setattr(h, "docker", docker)
    # No repo exists: controller never opens or queries it before the boundary.
    with pytest.raises(OBJECTS.Invalid):
        # load_objects creates a separate exception class, so use same verifier.
        monkeypatch.setattr(h, "load_objects", lambda: OBJECTS)
        h.acquire_sources(config, repo, CANDIDATE, BASE, root)
    assert calls[0][1]["output_limit"] == OBJECTS.MAX_BYTES
    assert calls[1][0][:2] == ("rm", "--force")
    assert calls[2][0][:2] == ("ps", "--all")
    assert not root.exists()


@pytest.mark.parametrize("stage", ["source", "worker"])
@pytest.mark.parametrize("stream", [1, 2])
def test_real_flood_is_killed_cleaned_and_never_creates_pass_receipt(
    tmp_path, monkeypatch, capsys, stream, stage
):
    from types import SimpleNamespace

    pid = tmp_path / "pid"
    code = (
        f"import os,pathlib; pathlib.Path({str(pid)!r}).write_text(str(os.getpid())); "
        f"exec('while True: os.write({stream}, b\"x\" * 4096)')"
    )
    calls = []
    monkeypatch.setattr(OBJECTS, "MAX_BYTES", 1024)
    monkeypatch.setattr(h, "load_objects", lambda: OBJECTS)
    monkeypatch.setattr(h, "installation", lambda: CONFIG | {"bundle": str(tmp_path)})
    monkeypatch.setattr(h, "signing_key", lambda: KEY)
    monkeypatch.setattr(h, "protected", lambda *a, **kw: None)
    # Emulate launch prerequisites only. Actual commands remain UID of builder.
    monkeypatch.setattr(h.os, "geteuid", lambda: 0)
    monkeypatch.setattr(h.sys, "flags", SimpleNamespace(isolated=1))
    monkeypatch.setattr(h.sys, "dont_write_bytecode", True)
    monkeypatch.setattr(h, "SCRATCH", tmp_path)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    monkeypatch.setattr(h, "RECEIPTS", receipts)
    if stage == "source":
        monkeypatch.setattr(h, "rehearse", lambda *a: pytest.fail("must refuse before export"))
    else:
        real_command = h.command

        def fictional_export(argv, **kw):
            if argv[0] == sys.executable and "--output" in argv:
                pair = Path(argv[argv.index("--output") + 1])
                pair.mkdir()
                (pair / "manifest.json").write_text("{}")
                return b""
            return real_command(argv, **kw)

        fake = SimpleNamespace()
        fake.rehearse = lambda _pair, _hash, _baseline, _chain, revision, source: fake.migrate(
            object(), {}, source, "upgrade", revision
        )
        monkeypatch.setattr(h, "command", fictional_export)
        monkeypatch.setattr(h, "acquire_sources", lambda *a: None)
        monkeypatch.setattr(h, "load_gate", lambda _: fake)
        monkeypatch.setattr(h, "migration_scope", lambda *a: ("0127", "0128", [object()]))

    def docker(*args, **kw):
        calls.append(args)
        if args[0] == "run":
            return h.command([sys.executable, "-IB", "-c", code], **(kw | {"output_limit": 1024}))
        return b""

    monkeypatch.setattr(h, "docker", docker)
    assert (
        h.main(
            [
                "rehearse",
                "--workbench",
                str(tmp_path / "repo"),
                "--candidate",
                CANDIDATE,
                "--base",
                BASE,
            ]
        )
        == 1
    )
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)
    assert calls[1][:2] == ("rm", "--force")
    assert calls[2][:2] == ("ps", "--all")
    assert not list(tmp_path.glob("run-*")) and not list(receipts.iterdir())
    assert "PASS" not in capsys.readouterr().out


def test_combined_stdout_stderr_limit_and_cleanup_failure(tmp_path, monkeypatch):
    with pytest.raises(h.Refusal, match="output exceeds"):
        h.command(
            [sys.executable, "-IB", "-c", "import os; os.write(1,b'x'*700); os.write(2,b'y'*700)"],
            output_limit=1024,
        )
    calls = []

    def docker(*args, **kw):
        calls.append(args)
        return b"still-running" if args[0] == "ps" else b""

    monkeypatch.setattr(h, "docker", docker)
    with pytest.raises(h.Refusal, match="cleanup not verified"):
        h.remove_container("fictional")
    assert len(calls) == 2


def test_real_bounded_command_streams_input_and_caps_timeout(tmp_path):
    data = b"x" * (1024 * 1024)
    assert (
        h.command(
            [sys.executable, "-IB", "-c", "import sys; print(len(sys.stdin.buffer.read()))"],
            data=data,
        )
        == b"1048576\n"
    )
    pid = tmp_path / "pid"
    with pytest.raises(h.Refusal, match="timed out"):
        h.command(
            [
                sys.executable,
                "-IB",
                "-c",
                f"import os,pathlib,time; pathlib.Path({str(pid)!r})"
                ".write_text(str(os.getpid())); time.sleep(20)",
            ],
            timeout=0.2,
        )
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)


def test_real_source_reader_container_with_fictional_git(tmp_path):
    image = os.environ.get("AC_TRUSTED_REHEARSAL_TEST_IMAGE")
    if not image:
        pytest.skip("requires approved Docker source-reader executor and Git-capable offline image")
    repo, base, candidate, _ = fictional_repo(tmp_path)
    fixture_git(repo, "config", "filter.evil.process", "exit 99")
    name = "ac-rehearsal-source-probe-" + h.uuid4().hex
    try:
        raw = h.docker(
            *h.source_reader_argv(
                repo, CONFIG | {"bundle": str(ROOT), "runner_image": image}, name, candidate, base
            ),
            output_limit=OBJECTS.MAX_BYTES,
        )
    finally:
        h.remove_container(name)
    objects = OBJECTS.read_bundle(raw)
    OBJECTS.ancestor(objects, candidate, base)
    OBJECTS.snapshot(objects, candidate, tmp_path / "snapshot")
    assert (tmp_path / "snapshot/payload.txt").read_bytes() == b"candidate raw $Id$\n"
