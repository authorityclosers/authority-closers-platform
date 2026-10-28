"""sx-web-bundle: the phone apps' signed web bundles (live web updates), as the apps check them."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/sx-web-bundle"
HOST = "salesxray.authorityclosers.com"
SHA = "4a6564b53e7a818649d4b023153473d415123408"
SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
# RFC 8032 test 1: the public key of SEED.
PUBLIC = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
PAGES = ("index.html", "dashboard/index.html", "leads/index.html", "chats/index.html")


def _tool() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("sx_web_bundle", str(SCRIPT))
    spec = importlib.util.spec_from_loader("sx_web_bundle", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


tool = _tool()


def _export(tmp_path: Path, extra: tuple[str, ...] = ()) -> Path:
    export = tmp_path / "out"
    for name in (
        *PAGES,
        "index.txt",
        "_next/static/chunks/app.js",
        "_next/static/css/a.css",
        *extra,
    ):
        (export / name).parent.mkdir(parents=True, exist_ok=True)
        (export / name).write_text(f"/* {name} */")
    return export


def _pack(tmp_path: Path, extra: tuple[str, ...] = ()) -> dict[str, object]:
    return tool.pack(
        _export(tmp_path, extra),
        tmp_path / "bundle",
        host=HOST,
        sha=SHA,
        ref="v1.3.0",
        commit_at_ms=1_761_650_000_000,
        built_at_ms=1_761_650_600_000,
    )


def _signed(
    tmp_path: Path, *, sequence: int = 7, min_native: int = 1
) -> tuple[dict[str, object], str]:
    facts = _pack(tmp_path)
    text = tool.payload_text(facts, version="1.3.0", sequence=sequence, min_native=min_native)
    envelope = tool.sign(text, tool.load_private_key(SEED))
    return facts, json.dumps(envelope)


def test_pack_prunes_like_the_app_build_and_names_the_zip_by_its_sha256(tmp_path: Path) -> None:
    facts = _pack(
        tmp_path,
        (
            "review-fixture/shell/index.html",
            "auth/complete/index.html",
            "organisation/invites/index.html",
            "provider-review/index.html",
            "_next/static/chunks/app.js.map",
            "brands/a.json",
            "brands/index.json",
            "developers/sx.py",
            "developers/__pycache__/sx.cpython-312.pyc",
        ),
    )
    zip_path = tmp_path / "bundle" / f"{facts['sha256']}.zip"
    assert facts["zip"] == zip_path.name
    assert facts["bytes"] == zip_path.stat().st_size
    assert tool.sha256_file(zip_path) == facts["sha256"]
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        web = json.loads(archive.read("sx-web.json"))
    assert names[-1] == "sx-web.json"
    assert "brands/index.json" in names
    for gone in (
        "review-fixture/",
        "auth/",
        "organisation/invites/",
        "provider-review/",
        ".map",
        "brands/a.json",
        "developers/",
    ):
        assert not any(gone in name for name in names), gone
    # sx-web.json is the app's own file list format (BundledWeb), with the commit's time.
    assert web["host"] == HOST and web["sha"] == SHA and web["commitAtMs"] == 1_761_650_000_000
    assert sorted(web["files"]) == sorted(name for name in names if name != "sx-web.json")


def test_the_zip_is_the_same_bytes_for_the_same_export(tmp_path: Path) -> None:
    first = _pack(tmp_path / "a")
    second = _pack(tmp_path / "b")
    assert first["sha256"] == second["sha256"]


@pytest.mark.parametrize(
    "native",
    [
        "lib/arm64-v8a/libsx.so",
        "classes.dex",
        "plugin.jar",
        "app.apk",
        "fast.wasm",
        "run.sh",
        "NOTES",
    ],
)
def test_no_native_code_or_unknown_file_ever_goes_in_a_bundle(tmp_path: Path, native: str) -> None:
    with pytest.raises(tool.BundleError, match="not a web file"):
        _pack(tmp_path, (native,))


def test_a_bundle_without_the_apps_pages_is_refused(tmp_path: Path) -> None:
    export = _export(tmp_path)
    (export / "leads" / "index.html").unlink()
    with pytest.raises(tool.BundleError, match="missing pages: leads/index.html"):
        tool.pack(
            export, tmp_path / "bundle", host=HOST, sha=SHA, ref="", commit_at_ms=1, built_at_ms=1
        )


def test_the_file_types_are_the_apps_list() -> None:
    # sales-xray-apps LiveWebRules.TYPES: change both together.
    assert {
        "html", "js", "mjs", "css", "json", "txt",
        "svg", "png", "jpg", "jpeg", "webp", "avif", "gif", "ico",
        "woff2", "woff", "ttf", "otf",
        "webmanifest", "xml", "csv", "pdf",
        "mp3", "mp4", "webm", "wav", "ogg", "m4a",
    } == tool.TYPES  # fmt: skip


def test_the_manifest_is_signed_as_the_app_checks_it(tmp_path: Path) -> None:
    facts, text = _signed(tmp_path)
    envelope = json.loads(text)
    assert set(envelope) == {"format", "key", "payload", "signature"}
    assert envelope["format"] == "sx-web-bundle/1"
    assert envelope["key"] == PUBLIC
    payload = json.loads(envelope["payload"])
    assert payload == {
        "host": HOST,
        "version": "1.3.0",
        "sha": SHA,
        "sequence": 7,
        "bundle": f"bundles/{facts['sha256']}.zip",
        "sha256": facts["sha256"],
        "bytes": facts["bytes"],
        "minNative": 1,
        "commitAtMs": 1_761_650_000_000,
        "builtAtMs": 1_761_650_600_000,
    }
    # Ed25519 over the format line, then the payload's exact text (LiveWebRules.open).
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(SEED)).public_key()
    key.verify(
        bytes.fromhex(envelope["signature"]), b"sx-web-bundle/1\n" + envelope["payload"].encode()
    )
    assert tool.open_manifest(text, [PUBLIC], HOST)["sha256"] == facts["sha256"]


def test_a_changed_manifest_another_key_or_another_site_is_refused(tmp_path: Path) -> None:
    _, text = _signed(tmp_path)
    envelope = json.loads(text)
    changed = dict(envelope, payload=envelope["payload"].replace('"minNative":1', '"minNative":0'))
    with pytest.raises(tool.BundleError, match="signature refused"):
        tool.open_manifest(json.dumps(changed), [PUBLIC], HOST)
    other = Ed25519PrivateKey.generate()
    with pytest.raises(tool.BundleError, match="isn't pinned"):
        tool.open_manifest(text, [tool.public_hex(other)], HOST)
    with pytest.raises(tool.BundleError, match="host"):
        tool.open_manifest(text, [PUBLIC], "salesxray-dev.authorityclosers.com")
    with pytest.raises(tool.BundleError, match="no public key"):
        tool.open_manifest(text, [], HOST)


def test_a_zip_that_isnt_the_manifests_is_refused(tmp_path: Path) -> None:
    facts, text = _signed(tmp_path)
    fields = tool.open_manifest(text, [PUBLIC], HOST)
    zip_path = tmp_path / "bundle" / f"{facts['sha256']}.zip"
    tool.check_zip(fields, zip_path)
    other = tmp_path / "other.zip"
    data = bytearray(zip_path.read_bytes())
    data[-30] ^= 1
    other.write_bytes(bytes(data))
    with pytest.raises(tool.BundleError, match="SHA-256"):
        tool.check_zip(fields, other)


def test_publish_puts_the_zip_in_place_before_the_manifest_and_keeps_the_newest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app-web"
    for old in range(4):
        (root / "bundles").mkdir(parents=True, exist_ok=True)
        stale = root / "bundles" / f"{old:064x}.zip"
        stale.write_bytes(b"old")
        os.utime(stale, (1_000_000 + old, 1_000_000 + old))
    facts, text = _signed(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(text)
    zip_path = tmp_path / "bundle" / f"{facts['sha256']}.zip"
    tool.publish(manifest, zip_path, root, PUBLIC, keep=3)
    assert (root / "manifest.json").read_text() == text
    published = root / "bundles" / f"{facts['sha256']}.zip"
    assert published.read_bytes() == zip_path.read_bytes()
    assert stat.S_IMODE(published.stat().st_mode) == 0o644
    assert stat.S_IMODE((root / "manifest.json").stat().st_mode) == 0o644
    remaining = sorted(path.name for path in (root / "bundles").glob("*.zip"))
    assert remaining == sorted([published.name, f"{3:064x}.zip", f"{2:064x}.zip"])
    assert not list(root.rglob(".*"))


def test_publish_refuses_a_manifest_the_apps_would_refuse(tmp_path: Path) -> None:
    facts, text = _signed(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(text)
    zip_path = tmp_path / "bundle" / f"{facts['sha256']}.zip"
    with pytest.raises(tool.BundleError):
        tool.publish(
            manifest,
            zip_path,
            tmp_path / "app-web",
            tool.public_hex(Ed25519PrivateKey.generate()),
            3,
        )
    assert not (tmp_path / "app-web" / "manifest.json").exists()


def _cli(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command, env=env, capture_output=True, text=True, timeout=60, check=False
    )


def test_signing_never_shows_the_key(tmp_path: Path) -> None:
    facts = _pack(tmp_path)
    bundle_json = tmp_path / "bundle" / "bundle.json"
    assert json.loads(bundle_json.read_text())["sha256"] == facts["sha256"]
    out = tmp_path / "manifest.json"
    env = dict(os.environ, AC_SX_WEB_BUNDLE_SIGNING_KEY=SEED)
    command = [sys.executable, str(SCRIPT), "sign", "--bundle-json", str(bundle_json)]
    command += ["--version", "1.3.0", "--sequence", "9", "--out", str(out)]
    done = _cli(command, env)
    assert done.returncode == 0, done.stderr
    assert SEED not in done.stdout + done.stderr + out.read_text()
    assert json.loads(done.stdout)["key"] == PUBLIC
    # A malformed key is named, never echoed.
    env["AC_SX_WEB_BUNDLE_SIGNING_KEY"] = SEED[:-2] + "zz"
    bad = _cli(command, env)
    assert bad.returncode == 1
    assert SEED[:20] not in bad.stdout + bad.stderr
    assert "is not an Ed25519 key" in bad.stderr
    env.pop("AC_SX_WEB_BUNDLE_SIGNING_KEY")
    missing = _cli(command, env)
    assert missing.returncode == 1 and "comes from Infisical" in missing.stderr
