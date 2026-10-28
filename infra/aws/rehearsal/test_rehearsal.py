"""Safety regression tests for disposable rehearsal tooling, no network or secrets."""

import runpy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent


def test_rehearsal_overlay_has_only_loopback_ingress_and_valid_tmpfs():
    # The real Compose engine handles !reset/!override; this loader checks the
    # original YAML scalar structure that caused an actual Docker startup failure.
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor(
        "!override",
        lambda loader, node: (
            loader.construct_sequence(node)
            if isinstance(node, yaml.SequenceNode)
            else loader.construct_mapping(node)
        ),
    )
    Loader.add_constructor("!reset", lambda loader, node: loader.construct_sequence(node))
    config = yaml.load(  # noqa: S506 - Loader subclasses SafeLoader
        (ROOT / "compose.rehearsal.yaml").read_text(), Loader=Loader
    )
    for name, service in config["services"].items():
        for publish in service.get("ports", []):
            assert publish.startswith("127.0.0.1:"), name
        for mount in service.get("tmpfs", []):
            assert mount.startswith("/"), (name, mount)
    assert config["networks"]["edge"]["internal"] is True
    assert config["services"]["api"]["networks"] == {"app": {}, "data": {}, "edge": {}}
    assert config["services"]["worker"]["networks"] == {"data": {}}


def test_setup_never_overwrites_existing_credentials(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(ROOT / "setup.py"))
    main = namespace["main"]
    main.__globals__["ROOT"] = tmp_path
    original = b"fixture placeholder, not a secret\n"
    target = tmp_path / "runtime.env"
    target.write_bytes(original)
    with pytest.raises(SystemExit, match="refusing credential replacement"):
        main()
    assert target.read_bytes() == original
    assert not (tmp_path / "approval.json").exists()


def test_probe_refuses_non_loopback_before_network(monkeypatch):
    namespace = runpy.run_path(str(ROOT / "probe.py"))
    monkeypatch.setattr("sys.argv", ["probe.py", "--url", "https://production.example.test"])
    with pytest.raises(SystemExit, match="SSH loopback required"):
        namespace["main"]()
