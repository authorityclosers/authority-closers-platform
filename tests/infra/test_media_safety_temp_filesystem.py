"""Opt-in, 32 MiB Linux loop-filesystem proof; never uses deployment paths."""

from __future__ import annotations

import errno
import importlib.util
import os
import re
import shutil
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.getenv("AC_SCANNER_LOOPBACK_TEST") != "1",
    reason="explicit Linux scanner loop-filesystem proof was not requested",
)


def test_real_fixed_filesystem_exhaustion_and_remount_preserve_host_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.geteuid() != 0:
        pytest.skip("scanner loop-filesystem proof requires root")
    capabilities = re.search(
        r"^CapEff:\s+([0-9a-f]+)$", Path("/proc/self/status").read_text(), re.MULTILINE
    )
    if capabilities is None or not int(capabilities[1], 16) & (1 << 21):
        pytest.skip("scanner loop-filesystem proof requires CAP_SYS_ADMIN")
    for command in ("mkfs.ext4", "mount", "umount", "findmnt", "losetup", "blockdev"):
        if shutil.which(command) is None:
            pytest.skip(f"scanner loop-filesystem proof requires {command}")
    spec = importlib.util.spec_from_file_location(
        "scanner_disk_proof", ROOT / "infra/media-safety/manage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.TEMP_CAPACITY_BYTES == 8 * 1024**3
    assert module.TEMP_MAX_QUEUE == 4
    managed = tmp_path / "managed"
    managed.mkdir(mode=0o700)
    mountpoint = tmp_path / "mount"
    image = managed / "scanner-temp-v1.ext4"
    monkeypatch.setattr(module, "ROOT", managed)
    monkeypatch.setattr(module, "TEMP_ROOT", mountpoint)
    monkeypatch.setattr(module, "TEMP_IMAGE", image)
    monkeypatch.setattr(module, "TEMP_CAPACITY_BYTES", 32 * 1024**2)
    monkeypatch.setattr(module, "TEMP_HOST_HEADROOM_BYTES", 2 * 1024**2)
    assert mountpoint.resolve().is_relative_to(tmp_path.resolve())
    assert image.resolve().is_relative_to(tmp_path.resolve())
    try:
        module.ensure_temp_root()
        module.validate_temp_root()
        allocated = image.stat().st_blocks
        filled = mountpoint / "retained-stream"
        written = 0
        with filled.open("wb", buffering=0) as stream, pytest.raises(OSError) as exhausted:
            while written <= module.TEMP_CAPACITY_BYTES:
                written += stream.write(b"x" * (1024**2))
        assert exhausted.value.errno == errno.ENOSPC
        assert 0 < written <= module.TEMP_CAPACITY_BYTES
        assert image.stat().st_size == module.TEMP_CAPACITY_BYTES
        assert image.stat().st_blocks == allocated
        retained_size = filled.stat().st_size
        module.run("umount", str(mountpoint))
        assert not os.path.ismount(mountpoint)
        assert stat.S_IMODE(mountpoint.stat().st_mode) == 0
        assert mountpoint.stat().st_uid == 0
        assert not tuple(mountpoint.iterdir())
        # Full retained filesystems must remount without fresh allocation or erasure.
        monkeypatch.setattr(
            module.os, "statvfs", lambda _path: pytest.fail("remount must reuse allocation")
        )
        module.ensure_temp_root()
        module.validate_temp_root()
        assert filled.stat().st_size == retained_size
        assert image.stat().st_blocks == allocated
        assert image.stat().st_size == module.TEMP_CAPACITY_BYTES
    finally:
        if os.path.ismount(mountpoint):
            # Cleanup only this newly created test mount, after checking its backing.
            mounted = module.json.loads(
                module.run(
                    "findmnt",
                    "--json",
                    "--mountpoint",
                    str(mountpoint),
                    "--output",
                    "TARGET,SOURCE,FSTYPE,OPTIONS",
                )
            )["filesystems"]
            assert len(mounted) == 1
            device = mounted[0]["source"]
            loops = module.json.loads(
                module.run(
                    "losetup",
                    "--json",
                    "--list",
                    "--output",
                    "NAME,BACK-FILE,OFFSET,SIZELIMIT,RO",
                    device,
                )
            )["loopdevices"]
            assert len(loops) == 1
            module.validate_temp_mount(mounted[0], loops[0])
            module.run("umount", str(mountpoint))
        assert not os.path.ismount(mountpoint)
