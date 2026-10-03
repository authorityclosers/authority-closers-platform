#!/usr/bin/python3
"""Sign a named fictional QA identity into Admin dev in a private browser for Browser QA.

Run as the non-root QA user (installed root-owned at
``/usr/local/libexec/ac-dev-qa/qa-admin-browser.py``)::

    /usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity billing-staff

Scope is fixed: Admin dev only (origin https://admin-dev.authorityclosers.com,
served through the CEO-approved loopback edge 127.0.0.1:3017), the allowlisted
fictional ``@example.test`` identities below, and a deployed admin-web revision
whose root-written receipt proves it contains the identity's required merges.
Anything else is refused before a credential is requested.

Order:
1. Preflight: non-root caller, identity, origin, deployed source pin, live edge.
2. Sentinel: the root broker sends a fresh fictional sentinel over the same pipe;
   it is typed into the real /login form, which must refuse it. The launcher then
   proves the sentinel is absent from every browser argv/environment, the
   profile files and its own output. Any leak or unexpected sign-in stops here.
3. Credential: the broker sends the real password over a pipe into this
   process's memory; it is typed into the real form over the DevTools pipe and
   the buffer is zeroed. The run passes only when ``/v1/me`` returns the named
   identity. No API, session or capability is mocked or bypassed.
4. Hand-off: prints the loopback DevTools URL for Browser QA (Playwright
   ``connectOverCDP``) and keeps the browser until Ctrl-C, SIGTERM or
   ``--hold-seconds``; then it stops the browser and deletes the profile.

The browser reaches the https origin through an in-process TLS bridge to the
loopback edge, trusted by the ephemeral certificate's SPKI pin only, so the real
Host, Origin and ``__Host-`` cookies apply. Output never contains a password,
cookie or token.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Identity:
    email: str
    folder: str
    secret: str
    required_merges: tuple[str, ...]


# Keep names, emails and secret references equal to the broker's table.
IDENTITIES = {
    "billing-staff": Identity(
        email="qa-billing-staff-aut959@example.test",
        folder="/sales-xray/dev-fixture-accounts",
        secret="AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF",  # noqa: S106 - a name, not a value
        # AUT-890: Admin Billing uses the staff refund route.
        required_merges=("1daeb17431a83a1330e9ec5f2362c29d3bb39c30",),
    ),
}
HOST = "admin-dev.authorityclosers.com"
ORIGIN = f"https://{HOST}"
EDGE_HOST, EDGE_PORT = "127.0.0.1", 3017
API_PORT = 8100  # the dev API behind the edge's /v1/* route
RECEIPT = Path("/var/lib/ac-dev-admin-web/deployed.json")
BROKER = ["sudo", "-n", "/usr/local/sbin/ac-dev-qa-credential"]
CHROME_CANDIDATES = (
    "~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome",
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
)
SIGN_IN_ERROR = "Sign-in was not confirmed"
SHA_RE = re.compile(r"[0-9a-f]{40}")


class Refused(RuntimeError):
    """A stable, value-free reason to stop."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(ok: bool, code: str) -> None:
    if not ok:
        raise Refused(code)


class Output:
    """Everything the launcher prints, kept so the leak check can scan it."""

    def __init__(self, stream=sys.stdout):
        self.stream = stream
        self.lines: list[str] = []

    def emit(self, **fields: Any) -> None:
        line = json.dumps(fields, sort_keys=True)
        self.lines.append(line)
        print(line, file=self.stream, flush=True)


# Preflight -------------------------------------------------------------------


def edge_request(path: str, port: int = EDGE_PORT, timeout: float = 10.0) -> tuple[int, bytes]:
    request = urllib.request.Request(f"http://{EDGE_HOST}:{port}{path}", headers={"Host": HOST})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read(65536)
    except urllib.error.HTTPError as error:
        return error.code, b""
    except OSError:
        return 0, b""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


def read_receipt(path: Path = RECEIPT) -> dict[str, Any]:
    try:
        info = path.lstat()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused("deployed_receipt_unreadable") from error
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0, "deployed_receipt_not_root")
    require(info.st_mode & 0o022 == 0, "deployed_receipt_writable")
    require(isinstance(data, dict), "deployed_receipt_invalid")
    return data


def preflight(
    identity_name: str, origin: str, *, receipt: dict[str, Any] | None = None, edge=edge_request
) -> dict[str, Any]:
    require(os.geteuid() != 0, "run_as_non_root")
    require(identity_name in IDENTITIES, "identity_not_allowed")
    identity = IDENTITIES[identity_name]
    require(identity.email.endswith("@example.test"), "identity_not_fictional")
    require(origin.rstrip("/") == ORIGIN, "origin_not_allowed")
    receipt = read_receipt() if receipt is None else receipt
    revision = str(receipt.get("revision", ""))
    require(receipt.get("host") == HOST, "deployed_receipt_wrong_host")
    require(SHA_RE.fullmatch(revision) is not None, "deployed_revision_invalid")
    contains = set(receipt.get("contains") or [])
    require(
        all(sha in contains for sha in identity.required_merges), "deployed_source_missing_merge"
    )
    status, _ = edge("/login")
    require(status == 200, "admin_dev_login_unavailable")
    status, _ = edge("/v1/me")
    require(status == 401, "admin_dev_api_route_unavailable")
    status, body = edge("/health/ready", API_PORT)
    try:
        ready = json.loads(body or b"{}").get("status") == "ready"
    except ValueError:
        ready = False
    require(status == 200 and ready, "admin_dev_api_not_ready")
    return {"identity": identity_name, "origin": ORIGIN, "admin_revision": revision}


# Credential transport --------------------------------------------------------


def broker_secret(identity_name: str, *, sentinel: bool, argv_prefix=BROKER) -> bytearray:
    """Read one value from the root broker's stdout pipe into memory."""

    argv = [*argv_prefix, identity_name] + (["--sentinel"] if sentinel else [])
    process = subprocess.Popen(  # noqa: S603 - fixed argv; the value never enters it.
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    value = bytearray()
    assert process.stdout is not None
    while chunk := process.stdout.read(512):
        value += chunk
        if len(value) > 512:
            break
    _, error = process.communicate(timeout=90)
    if process.returncode != 0 or not value or len(value) > 512:
        value[:] = b"\0" * len(value)
        reason = re.search(rb"refused: ([a-z_]+)", error or b"")
        raise Refused("broker_" + (reason.group(1).decode() if reason else "failed"))
    return value


def json_string(value: bytearray) -> bytearray:
    """JSON-encode printable ASCII bytes without creating an immutable copy."""

    out = bytearray(b'"')
    for byte in value:
        require(0x20 <= byte < 0x7F, "secret_not_printable")
        if byte in (0x22, 0x5C):
            out.append(0x5C)
        out.append(byte)
    out.append(0x22)
    return out


# TLS bridge to the loopback edge ---------------------------------------------


def ephemeral_certificate(directory: Path) -> tuple[Path, Path, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "bridge.crt", directory / "bridge.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return cert_path, key_path, base64.b64encode(hashlib.sha256(spki).digest()).decode()


class Bridge:
    """TLS listener on an ephemeral loopback port forwarding to the edge."""

    def __init__(self, cert: Path, key: Path):
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.context.set_alpn_protocols(["http/1.1"])
        self.server = socket.create_server((EDGE_HOST, 0))
        self.port = self.server.getsockname()[1]
        self.stopped = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._accept, daemon=True).start()

    def stop(self) -> None:
        self.stopped.set()
        self.server.close()

    def _accept(self) -> None:
        while not self.stopped.is_set():
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket) -> None:
        try:
            tls = self.context.wrap_socket(client, server_side=True)
            upstream = socket.create_connection((EDGE_HOST, EDGE_PORT), timeout=30)
        except OSError:
            client.close()
            return
        threading.Thread(target=_pump, args=(upstream, tls), daemon=True).start()
        _pump(tls, upstream)


def _pump(source: socket.socket, target: socket.socket) -> None:
    try:
        while data := source.recv(65536):
            target.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (source, target):
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)


# Browser over the DevTools pipe ----------------------------------------------


def find_chrome(explicit: str | None) -> str:
    candidates = [explicit] if explicit else []
    for pattern in CHROME_CANDIDATES:
        candidates += sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    raise Refused("browser_not_found")


def chrome_argv(chrome: str, profile: Path, bridge_port: int, spki: str) -> list[str]:
    return [
        chrome,
        "--headless=new",
        # The host disables unprivileged user namespaces (AppArmor); this matches
        # Playwright's default Chromium launch here. Navigation stays on ORIGIN.
        "--no-sandbox",
        f"--user-data-dir={profile}",
        "--remote-debugging-pipe",
        "--remote-debugging-port=0",
        f"--host-resolver-rules=MAP {HOST} {EDGE_HOST}:{bridge_port}",
        f"--ignore-certificate-errors-spki-list={spki}",
        "--disable-quic",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--password-store=basic",
        "--disable-features=PasswordManagerOnboarding,AutofillServerCommunication",
        "about:blank",
    ]


def write_preferences(profile: Path) -> None:
    default = profile / "Default"
    default.mkdir(parents=True, mode=0o700)
    preferences = {
        "credentials_enable_service": False,
        "profile": {"password_manager_enabled": False},
        "autofill": {"profile_enabled": False, "credit_card_enabled": False},
    }
    (default / "Preferences").write_text(json.dumps(preferences), encoding="utf-8")


def _high_fd(fd: int) -> int:
    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10)
    os.close(fd)
    return moved


class Browser:
    def __init__(self, chrome: str, profile: Path, bridge_port: int, spki: str):
        write_preferences(profile)
        to_chrome_r, self._write = (_high_fd(fd) for fd in os.pipe())
        self._read, from_chrome_w = (_high_fd(fd) for fd in os.pipe())
        # The shell moves the DevTools pipe ends (all >= 10, so never 3/4) to
        # fds 3/4 and execs the browser.
        wire = f'exec "$@" 3<&{to_chrome_r} 4>&{from_chrome_w} {to_chrome_r}<&- {from_chrome_w}>&-'
        clean_env = {
            k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LD_LIBRARY_PATH") if k in os.environ
        }
        self.process = subprocess.Popen(  # noqa: S603 - fixed argv without any credential.
            ["/bin/bash", "-c", wire, "bash", *chrome_argv(chrome, profile, bridge_port, spki)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env,
            pass_fds=(to_chrome_r, from_chrome_w),
        )
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self.profile = profile
        self._buffer = bytearray()
        self._next = 0
        self.session = ""

    def _send(self, payload: bytearray) -> None:
        view = memoryview(payload + b"\0")
        while view:
            view = view[os.write(self._write, view) :]

    def _receive(self, wanted: int, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            while b"\0" in self._buffer:
                raw, _, rest = bytes(self._buffer).partition(b"\0")
                self._buffer = bytearray(rest)
                message = json.loads(raw)
                if message.get("id") == wanted:
                    if "error" in message:
                        raise Refused("browser_command_refused")
                    return message.get("result", {})
            require(time.monotonic() < deadline, "browser_timeout")
            chunk = os.read(self._read, 1 << 16)
            require(bool(chunk), "browser_exited")
            self._buffer += chunk

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        self._next += 1
        message: dict[str, Any] = {"id": self._next, "method": method, "params": params or {}}
        if session and self.session:
            message["sessionId"] = self.session
        self._send(bytearray(json.dumps(message).encode()))
        return self._receive(self._next, timeout)

    def insert_secret(self, value: bytearray) -> None:
        """``Input.insertText`` built from the mutable buffer; no str copy of the value."""

        self._next += 1
        head = json.dumps(
            {"id": self._next, "method": "Input.insertText", "sessionId": self.session}
        )
        encoded = json_string(value)
        payload = bytearray(head[:-1].encode()) + b', "params": {"text": ' + encoded + b"}}"
        try:
            self._send(payload)
        finally:
            encoded[:] = b"\0" * len(encoded)
            payload[:] = b"\0" * len(payload)
        self._receive(self._next, 30.0)

    def open_page(self) -> None:
        page = self.call("Target.createTarget", {"url": "about:blank"}, session=False)
        attached = self.call(
            "Target.attachToTarget", {"targetId": page["targetId"], "flatten": True}, session=False
        )
        self.session = attached["sessionId"]

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result:
            return None
        return result.get("result", {}).get("value")

    def until(self, expression: str, timeout: float = 30.0) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(expression)
            if value:
                return value
            time.sleep(0.25)
        raise Refused("browser_state_timeout")

    def devtools_url(self, timeout: float = 15.0) -> str:
        active = self.profile / "DevToolsActivePort"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if active.is_file():
                port = active.read_text().splitlines()[0].strip()
                if port.isdigit():
                    return f"http://127.0.0.1:{port}"
            time.sleep(0.2)
        raise Refused("devtools_port_unavailable")

    def descendants(self) -> list[int]:
        pids, frontier = [], [self.process.pid]
        while frontier:
            pid = frontier.pop()
            pids.append(pid)
            try:
                children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
            except OSError:
                children = []
            frontier += [int(c) for c in children]
        return pids

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        for fd in (self._read, self._write):
            with contextlib.suppress(OSError):
                os.close(fd)


EMAIL_SELECTOR = "#operations-email"
PASSWORD_SELECTOR = "#operations-password"  # noqa: S105 - a CSS selector
READY_JS = (
    f"(() => {{ const b = document.querySelector('{PASSWORD_SELECTOR}')?.form"
    "?.querySelector('button.dev-admin-login-submit, button:not([type=button])');"
    " return !!b && !b.disabled; })()"
)
SUBMIT_JS = f"document.querySelector('{PASSWORD_SELECTOR}').form.requestSubmit()"
ME_JS = (
    "fetch('/v1/me', {credentials: 'same-origin', cache: 'no-store'})"
    ".then(r => r.ok ? r.json().then(j => 'me:' + j.email) : 'status:' + r.status)"
    ".catch(() => 'status:0')"
)
REFUSED_JS = (
    "Array.from(document.querySelectorAll('[role=alert]'))"
    f".some(e => e.textContent.includes({json.dumps(SIGN_IN_ERROR)}))"
)


def sign_in(browser: Browser, identity: Identity, secret: bytearray) -> str:
    """Type into the real /login form; return ``signed_in`` or ``refused``."""

    browser.open_page()
    browser.call("Page.enable")
    browser.call("Page.navigate", {"url": f"{ORIGIN}/login"})
    browser.until(f"location.origin === {json.dumps(ORIGIN)} && {READY_JS}")
    browser.evaluate(f"document.querySelector('{EMAIL_SELECTOR}').focus()")
    browser.call("Input.insertText", {"text": identity.email})
    browser.evaluate(f"document.querySelector('{PASSWORD_SELECTOR}').focus()")
    browser.insert_secret(secret)
    browser.evaluate(SUBMIT_JS)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if browser.evaluate(REFUSED_JS):
            return "refused"
        me = browser.evaluate(ME_JS)
        if me == f"me:{identity.email}":
            return "signed_in"
        require(not (isinstance(me, str) and me.startswith("me:")), "signed_in_as_other_identity")
        time.sleep(0.5)
    raise Refused("sign_in_outcome_timeout")


# Leak checks -----------------------------------------------------------------


def leak_locations(
    value: bytes | bytearray, pids: list[int], profile: Path, printed: list[str]
) -> list[str]:
    """Where ``value`` appears among argv, environments, profile files and output."""

    found = []
    if value in b"\0".join(a.encode() for a in sys.argv) or value in "\n".join(printed).encode():
        found.append("launcher")
    for pid in pids:
        for name in ("cmdline", "environ"):
            try:
                if value in Path(f"/proc/{pid}/{name}").read_bytes():
                    found.append(f"process_{name}")
            except OSError:
                pass
    for path in profile.rglob("*") if profile.is_dir() else []:
        try:
            if path.is_file() and not path.is_symlink() and value in path.read_bytes():
                found.append("profile_file")
                break
        except OSError:
            pass
    return sorted(set(found))


# Orchestration ---------------------------------------------------------------


def run_phase(
    chrome: str,
    workdir: Path,
    name: str,
    identity: Identity,
    secret: bytearray,
    bridge: Bridge,
    spki: str,
    output: Output,
) -> tuple[Browser, str]:
    """Sign in with ``secret`` and prove it leaked nowhere; always zero the buffer.

    The sentinel browser is stopped before its profile is scanned, so flushed
    files are covered too; the QA browser keeps running for the hand-off.
    """

    profile = workdir / f"profile-{name}"
    browser = Browser(chrome, profile, bridge.port, spki)
    try:
        outcome = sign_in(browser, identity, secret)
        pids = browser.descendants()
        if name == "sentinel":
            leaks = leak_locations(secret, pids, Path("/nonexistent"), output.lines)
            browser.stop()
            leaks += leak_locations(secret, [], profile, [])
        else:
            leaks = leak_locations(secret, pids, profile, output.lines)
    except BaseException:
        browser.stop()
        raise
    finally:
        secret[:] = b"\0" * len(secret)
    if leaks:
        browser.stop()
        raise Refused(f"{name}_leak_detected:" + ",".join(sorted(set(leaks))))
    return browser, outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--identity", required=True)
    parser.add_argument("--origin", default=ORIGIN)
    parser.add_argument("--sentinel-only", action="store_true")
    parser.add_argument("--hold-seconds", type=int, default=3600)
    parser.add_argument("--chrome")
    args = parser.parse_args(argv)
    output = Output()
    workdir: Path | None = None
    browser: Browser | None = None
    bridge: Bridge | None = None
    try:
        pin = preflight(args.identity, args.origin)
        output.emit(phase="preflight", ok=True, **pin)
        identity = IDENTITIES[args.identity]
        chrome = find_chrome(args.chrome)
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        workdir = Path(tempfile.mkdtemp(prefix="ac-dev-qa-", dir=runtime if runtime else None))
        workdir.chmod(0o700)
        cert, key, spki = ephemeral_certificate(workdir)
        bridge = Bridge(cert, key)
        bridge.start()

        sentinel = broker_secret(args.identity, sentinel=True)
        sentinel_browser, outcome = run_phase(
            chrome, workdir, "sentinel", identity, sentinel, bridge, spki, output
        )
        sentinel_browser.stop()
        shutil.rmtree(workdir / "profile-sentinel", ignore_errors=True)
        require(outcome == "refused", "sentinel_not_refused")
        output.emit(phase="sentinel", ok=True, login="refused", leaks=[])
        if args.sentinel_only:
            return 0

        secret = broker_secret(args.identity, sentinel=False)
        browser, outcome = run_phase(chrome, workdir, "qa", identity, secret, bridge, spki, output)
        require(outcome == "signed_in", "credential_sign_in_refused")
        output.emit(
            phase="handoff",
            ok=True,
            identity=args.identity,
            email=identity.email,
            origin=ORIGIN,
            devtools=browser.devtools_url(),
            admin_revision=pin["admin_revision"],
            hold_seconds=args.hold_seconds,
        )
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        with contextlib.suppress(KeyboardInterrupt):
            stop.wait(args.hold_seconds)
        return 0
    except Refused as error:
        output.emit(phase="refused", ok=False, error=error.code)
        return 1
    finally:
        if browser is not None:
            browser.stop()
        if bridge is not None:
            bridge.stop()
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
