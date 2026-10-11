"""Export committed source and reuse installed tools without live workspace links."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class SnapshotError(RuntimeError):
    """A source export or dependency link could not be safely prepared."""


@dataclass(frozen=True)
class Snapshot:
    root: Path
    sources: tuple[str, ...]
    sha256: str
    node_hook_sha256: str

    def unchanged(self) -> bool:
        return (
            source_digest(self.root, self.sources) == self.sha256
            and hashlib.sha256((self.root / ".ac-fast-node-source.cjs").read_bytes()).hexdigest()
            == self.node_hook_sha256
        )


def node_source_hook(workbench: Path, snapshot: Path) -> Path:
    """Redirect workspace source without duplicating third-party module identities."""
    hook = snapshot / ".ac-fast-node-source.cjs"
    hook.write_text(
        """const { createRequire, isBuiltin, registerHooks } = require('node:module');
const { fileURLToPath, pathToFileURL } = require('node:url');
const path = require('node:path');
const workbench = __WORKBENCH__;
const snapshot = __SNAPSHOT__;
function exported(value, dependencies = false) {
  if (typeof value !== 'string') return value;
  const isURL = value.startsWith('file:');
  if (!isURL && !path.isAbsolute(value)) return value;
  const relative = path.relative(workbench, isURL ? fileURLToPath(value) : value);
  if (relative === '..' || relative.startsWith('../') || path.isAbsolute(relative)) return value;
  if (!dependencies && relative.split(path.sep).includes('node_modules')) return value;
  const target = path.join(snapshot, relative);
  return isURL ? pathToFileURL(target).href : target;
}
registerHooks({
  resolve(specifier, context, nextResolve) {
    const pinned = { ...context, parentURL: exported(context.parentURL, true) };
    const required = context.conditions.includes('require');
    const name = exported(specifier);
    const target = required && pinned.parentURL !== context.parentURL && !isBuiltin(name)
      ? createRequire(pinned.parentURL).resolve(name) : name;
    const result = nextResolve(target, pinned);
    const url = exported(result.url);
    return url === result.url ? result
      : nextResolve(required && url.startsWith('file:') ? fileURLToPath(url) : url, pinned);
  },
  load(url, context, nextLoad) {
    return nextLoad(exported(url), context);
  }
});
""".replace("__WORKBENCH__", json.dumps(str(workbench))).replace(
            "__SNAPSHOT__", json.dumps(str(snapshot))
        ),
        encoding="utf-8",
    )
    return hook


def source_digest(root: Path, sources: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in sources:
        path = root / relative
        digest.update(relative.encode("utf-8") + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.readlink(path).encode("utf-8"))
        else:
            digest.update(b"file\0" + path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def dependency_link(source: Path, target: Path, workbench: Path, snapshot: Path) -> None:
    resolved = source.resolve()
    if resolved.is_relative_to(workbench):
        relative = resolved.relative_to(workbench)
        if "node_modules" not in relative.parts:
            resolved = snapshot / relative
            if not resolved.exists():
                raise SnapshotError("An installed workspace link has no committed source")
    target.symlink_to(resolved, target_is_directory=resolved.is_dir())


def installed_node_modules(source: Path, target: Path, workbench: Path, snapshot: Path) -> None:
    """Keep package links, wrapper paths and writable caches inside the export."""
    target.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir()):
        destination = target / entry.name
        if entry.name in {".cache", ".vite", ".vite-temp"}:
            continue
        if entry.name == ".bin" and entry.is_dir():
            destination.mkdir()
            for binary in sorted(entry.iterdir()):
                try:
                    text = binary.read_text(encoding="utf-8")
                except UnicodeError:
                    dependency_link(binary, destination / binary.name, workbench, snapshot)
                    continue
                wrapper = destination / binary.name
                wrapper.write_text(text.replace(str(workbench), str(snapshot)), encoding="utf-8")
                wrapper.chmod(binary.stat().st_mode & 0o777)
        elif entry.name == ".pnpm" and entry.is_dir():
            destination.mkdir()
            for package in sorted(entry.iterdir()):
                package_target = destination / package.name
                if package.name == "node_modules":
                    installed_node_modules(package, package_target, workbench, snapshot)
                elif package.is_dir() and not package.is_symlink():
                    package_target.mkdir()
                    for child in sorted(package.iterdir()):
                        if child.name == "node_modules" and child.is_dir():
                            installed_node_modules(
                                child, package_target / child.name, workbench, snapshot
                            )
                        else:
                            dependency_link(child, package_target / child.name, workbench, snapshot)
                else:
                    dependency_link(package, package_target, workbench, snapshot)
        elif entry.name.startswith("@") and entry.is_dir() and not entry.is_symlink():
            installed_node_modules(entry, destination, workbench, snapshot)
        else:
            dependency_link(entry, destination, workbench, snapshot)


@contextmanager
def committed_snapshot(workbench: Path, commit: str) -> Iterator[Snapshot]:
    executable = shutil.which("git")
    if executable is None:
        raise SnapshotError("Git is required to export committed source")
    with tempfile.TemporaryDirectory(prefix="ac-fast-source-", dir="/tmp") as temporary:
        directory = Path(temporary)
        root = directory / "source"
        root.mkdir()
        archive_path = directory / "source.tar"
        try:
            with archive_path.open("wb") as output:
                result = subprocess.run(  # noqa: S603 - fixed local git archive, no shell
                    [executable, "-C", str(workbench), "archive", "--format=tar", commit],
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    check=False,
                )
            if result.returncode:
                raise SnapshotError("Committed source could not be exported")
            with tarfile.open(archive_path) as archive:
                sources = tuple(sorted(member.name for member in archive if not member.isdir()))
                archive.extractall(root, filter="data")
            for relative in sources:
                path = root / relative
                if not path.resolve().is_relative_to(root):
                    raise SnapshotError("Committed source links must stay inside the export")
            sha256 = source_digest(root, sources)
            archive_path.unlink()
            environment = workbench / ".venv"
            if environment.is_dir():
                (root / ".venv").symlink_to(environment, target_is_directory=True)
            directories = [
                root,
                *(root / "apps").glob("*-web"),
                *(root / "packages/typescript").glob("*"),
            ]
            for directory_path in directories:
                relative_directory = directory_path.relative_to(root)
                installed = workbench / relative_directory / "node_modules"
                if directory_path.is_dir() and installed.is_dir():
                    installed_node_modules(
                        installed, directory_path / "node_modules", workbench, root
                    )
            hook = node_source_hook(workbench, root)
            yield Snapshot(root, sources, sha256, hashlib.sha256(hook.read_bytes()).hexdigest())
        except (OSError, tarfile.TarError) as error:
            raise SnapshotError(
                f"Committed source could not be prepared ({type(error).__name__})"
            ) from None
