"""Trusted raw-object reader and verifier; never load workbench Git configuration.

The export entry point runs ONLY inside the non-root, network-none source reader.
The controller consumes the bounded protocol and independently verifies every OID.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_BYTES = 128 * 1024 * 1024
MAX_OBJECT = 16 * 1024 * 1024
MAX_OBJECTS = 100_000
MAX_DEPTH = 128
OID = re.compile(r"[0-9a-f]{40}")
ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent",
    "LANG": "C.UTF-8",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
}


class Invalid(ValueError):
    pass


def verify(oid: str, kind: str, raw: bytes) -> None:
    if not OID.fullmatch(oid) or kind not in {"commit", "tree", "blob"}:
        raise Invalid("invalid raw object identity")
    if (
        len(raw) > MAX_OBJECT
        or hashlib.sha1(  # noqa: S324 - Git SHA1 object identity
            f"{kind} {len(raw)}\0".encode() + raw
        ).hexdigest()
        != oid
    ):
        raise Invalid("raw object digest mismatch or size exceeded")


def commit(raw: bytes) -> tuple[str, list[str]]:
    headers = raw.split(b"\n\n", 1)[0].splitlines()
    if not headers or not re.fullmatch(rb"tree [0-9a-f]{40}", headers[0]):
        raise Invalid("invalid commit tree")
    parents = []
    for line in headers[1:]:
        if line.startswith(b"parent "):
            if not re.fullmatch(rb"parent [0-9a-f]{40}", line):
                raise Invalid("invalid commit parent")
            parents.append(line[7:].decode("ascii"))
    return headers[0][5:].decode("ascii"), parents


def tree(raw: bytes):
    offset, names = 0, set()
    while offset < len(raw):
        end = raw.find(b"\0", offset)
        if end < 0 or end + 21 > len(raw):
            raise Invalid("invalid tree framing")
        mode, separator, name = raw[offset:end].partition(b" ")
        if (
            not separator
            or mode not in {b"40000", b"100644", b"100755"}
            or not name
            or len(name) > 255
            or name.lower() in {b".", b"..", b".git"}
            or b"/" in name
            or name in names
        ):
            raise Invalid("unsafe raw tree path or link")
        names.add(name)
        yield mode, os.fsdecode(name), raw[end + 1 : end + 21].hex()
        offset = end + 21


def read_bundle(raw: bytes) -> dict[str, tuple[str, bytes]]:
    if len(raw) > MAX_BYTES:
        raise Invalid("object bundle exceeds bound")
    objects = {}
    stream = io.BytesIO(raw)
    while header := stream.readline(128):
        if not re.fullmatch(rb"[0-9a-f]{40} (commit|tree|blob) [0-9]{1,9}\n", header):
            raise Invalid("invalid object framing")
        oid, kind, length = header.decode("ascii").split()
        size = int(length)
        if size > MAX_OBJECT:
            raise Invalid("raw object exceeds bound")
        data = stream.read(size)
        if len(data) != size or stream.read(1) != b"\n":
            raise Invalid("truncated object")
        verify(oid, kind, data)
        if oid in objects or len(objects) >= MAX_OBJECTS:
            raise Invalid("duplicate or excessive objects")
        objects[oid] = kind, data
    return objects


def value(objects, oid: str, kind: str) -> bytes:
    if oid not in objects or objects[oid][0] != kind:
        raise Invalid("required raw object missing or wrong type")
    return objects[oid][1]


def ancestor(objects, candidate: str, base: str) -> None:
    pending, seen = [candidate], set()
    while pending:
        oid = pending.pop()
        if oid == base:
            value(objects, base, "commit")
            return
        if oid in seen:
            continue
        seen.add(oid)
        if oid in objects:
            pending.extend(commit(value(objects, oid, "commit"))[1])
    raise Invalid("base is not a verified ancestor")


def snapshot(objects, oid: str, target: Path) -> None:
    root = commit(value(objects, oid, "commit"))[0]
    target.mkdir(mode=0o755)
    pending, count, total = [(root, target, 0)], 0, 0
    while pending:
        node, directory, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise Invalid("source tree depth exceeds bound")
        for mode, name, child in tree(value(objects, node, "tree")):
            count += 1
            if count > MAX_OBJECTS:
                raise Invalid("source file count exceeds bound")
            path = directory / name
            if mode == b"40000":
                path.mkdir(mode=0o755)
                pending.append((child, path, depth + 1))
            else:
                raw = value(objects, child, "blob")
                total += len(raw)
                if total > MAX_BYTES:
                    raise Invalid("materialized source exceeds bound")
                with path.open("xb") as out:
                    out.write(raw)
                path.chmod(0o755 if mode == b"100755" else 0o644)


def export(object_store: Path, candidate: str, base: str, output) -> None:
    """Read raw objects through a fresh Git dir; source config/refs/info are absent.

    Only object fanouts and pack storage are exposed to cat-file. In particular,
    source objects/info/alternates, config, shallow/grafts, refs/replace and
    attributes are never consulted. All Git calls stay inside the source sandbox.
    """
    if not OID.fullmatch(candidate) or not OID.fullmatch(base):
        raise Invalid("full candidate/base IDs required")
    with tempfile.TemporaryDirectory(prefix="raw-git-") as temporary:
        clean = Path(temporary)
        (clean / "refs").mkdir()
        (clean / "HEAD").write_text("ref: refs/heads/unused\n")
        store = clean / "objects"
        store.mkdir()
        (store / "info").mkdir()
        source = object_store
        for name in [f"{i:02x}" for i in range(256)] + ["pack"]:
            (store / name).symlink_to(source / name, target_is_directory=True)
        argv = ["/usr/bin/git", "--no-replace-objects", f"--git-dir={clean}", "cat-file"]
        # Batch stdout is consumed exactly by its declared size, before allocation.
        # No candidate-controlled stderr is retained; external controller caps all
        # reader output and its time. The reader itself has memory/PID/CPU limits.
        with subprocess.Popen(  # noqa: S603 - fixed Git command in unprivileged sandbox
            [*argv, "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=ENV,
            cwd=clean,
        ) as process:
            emitted, seen = 0, {}

            def get(oid, kind):
                nonlocal emitted
                if oid in seen:
                    if seen[oid][0] != kind:
                        raise Invalid("object type mismatch")
                    return seen[oid][1]
                if len(seen) >= MAX_OBJECTS:
                    raise Invalid("object count exceeded")
                process.stdin.write(oid.encode("ascii") + b"\n")
                process.stdin.flush()
                header = process.stdout.readline(128)
                if not re.fullmatch(
                    oid.encode() + b" " + kind.encode() + rb" [0-9]{1,9}\n", header
                ):
                    raise Invalid("missing or invalid raw object")
                size = int(header.split()[2])
                if size > MAX_OBJECT or emitted + len(header) + size + 1 > MAX_BYTES:
                    raise Invalid("raw object acquisition exceeds bound")
                raw = process.stdout.read(size)
                if len(raw) != size or process.stdout.read(1) != b"\n":
                    raise Invalid("truncated raw object")
                verify(oid, kind, raw)
                emitted += len(header) + size + 1
                output.write(header)
                output.write(raw)
                output.write(b"\n")
                # Blobs are streamed once and need not remain in reader memory.
                seen[oid] = kind, raw if kind != "blob" else b""
                return raw

            try:
                pending, visited = [candidate], set()
                found = False
                while pending:
                    oid = pending.pop()
                    if oid in visited:
                        continue
                    visited.add(oid)
                    _, parents = commit(get(oid, "commit"))
                    if oid == base:
                        found = True
                        break
                    pending.extend(parents)
                if not found:
                    raise Invalid("base is not an ancestor")
                for revision in {candidate, base}:
                    pending = [(commit(get(revision, "commit"))[0], 0)]
                    expanded = set()
                    while pending:
                        oid, depth = pending.pop()
                        if depth > MAX_DEPTH:
                            raise Invalid("source tree depth exceeded")
                        if oid in expanded:
                            continue
                        expanded.add(oid)
                        for mode, _, child in tree(get(oid, "tree")):
                            if mode == b"40000":
                                pending.append((child, depth + 1))
                            else:
                                get(child, "blob")
            finally:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    try:
        export(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.stdout.buffer)
    except Exception:
        # No source names, config or Git diagnostic output leaves the boundary.
        sys.exit(1)
