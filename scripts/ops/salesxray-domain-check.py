#!/usr/bin/env python3
"""Check Sales X-Ray on each of its addresses: the old one and salesxray.in (owner, 2 Nov 2026).

Read-only. By default every request goes to the public address (through Cloudflare). With --edge
it asks the edge router on ac directly with Host headers: the dark-launch check of the new
addresses before any DNS or tunnel hostname exists.

    salesxray-domain-check.py --edge http://127.0.0.1:8080        # dark launch, on ac
    salesxray-domain-check.py                                     # public, both families
    salesxray-domain-check.py --watch /var/lib/ac-domain-watch    # the five-minute monitor

--deep adds the rows that need a secret, when it is in the environment (ac-infisical-run injects
it; nothing here prints it): SX_CHECK_API_KEY (an sxk_ key) for /v1/api/me and the MCP tool list,
SX_CHECK_META_VERIFY_TOKEN and SX_CHECK_WHATSAPP_VERIFY_TOKEN for the webhook handshakes. It also
starts a Google sign-in (no account is touched) to read the redirect it asks Google for.

Exit 0 only when every check passed. With --watch it keeps a count per check in that directory
and prints ALERT the second time in a row a check fails and RECOVERED when it passes again
(--notify runs a command with that line). After --until (YYYY-MM-DD, UTC) it does nothing.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

ROUTE = "x-authority-closers-route"
FAMILIES: dict[str, dict[str, object]] = {
    # The old address serves its API and MCP itself, for good.
    "old": {
        "app": "salesxray.authorityclosers.com",
        "api": "salesxray.authorityclosers.com",
        "mcp": "salesxray.authorityclosers.com",
        "forward": (),
    },
    # The customer domain; salesxray.in and www forward to the app until the landing site is live.
    "new": {
        "app": "app.salesxray.in",
        "api": "api.salesxray.in",
        "mcp": "mcp.salesxray.in",
        "forward": ("salesxray.in", "www.salesxray.in"),
    },
}

Result = tuple[bool, str]


class Client:
    """One request at a time, never following redirects, to the public host or the edge."""

    def __init__(self, edge: str | None, timeout: float) -> None:
        self.edge = urlsplit(edge) if edge else None
        self.timeout = timeout

    def __call__(
        self,
        host: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection: http.client.HTTPConnection
        if self.edge is None:
            connection = http.client.HTTPSConnection(host, timeout=self.timeout)
        else:
            connection = http.client.HTTPConnection(
                self.edge.hostname or "127.0.0.1", self.edge.port or 80, timeout=self.timeout
            )
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={"Host": host, "User-Agent": "ac-domain-check/1", **(headers or {})},
            )
            response = connection.getresponse()
            data = response.read(256 * 1024)
            return response.status, {k.lower(): v for k, v in response.getheaders()}, data
        finally:
            connection.close()


def _json(data: bytes) -> dict[str, object]:
    try:
        value = json.loads(data)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def checks(
    family: str, get: Client, *, deep: bool, forward: bool
) -> list[tuple[str, Callable[[], Result]]]:
    names = FAMILIES[family]
    app, api, mcp = str(names["app"]), str(names["api"]), str(names["mcp"])
    found: list[tuple[str, Callable[[], Result]]] = []

    def page() -> Result:
        status, headers, _ = get(app, "GET", "/login")
        route = headers.get(ROUTE, "-")
        return status == 200 and route.startswith("sales-xray-"), f"{status} {route}"

    def resource() -> Result:
        status, _, data = get(mcp, "GET", "/.well-known/oauth-protected-resource/v1/mcp")
        meta = _json(data)
        ok = (
            status == 200
            and meta.get("resource") == f"https://{mcp}/v1/mcp"
            and meta.get("authorization_servers") == [f"https://{app}"]
        )
        return ok, f"{status} {meta.get('resource')} via {meta.get('authorization_servers')}"

    def issuer() -> Result:
        status, _, data = get(app, "GET", "/.well-known/oauth-authorization-server")
        meta = _json(data)
        return status == 200 and meta.get(
            "issuer"
        ) == f"https://{app}", f"{status} {meta.get('issuer')}"

    def challenge() -> Result:
        status, headers, _ = get(
            mcp, "POST", "/v1/mcp", headers={"Content-Type": "application/json"}, body=b"{}"
        )
        wanted = f'resource_metadata="https://{mcp}/.well-known/oauth-protected-resource/v1/mcp"'
        return status == 401 and wanted in headers.get("www-authenticate", ""), f"{status}"

    def webhook(path: str, token: str | None) -> Callable[[], Result]:
        def run() -> Result:
            echo = secrets.token_hex(8)
            query = urlencode(
                {
                    "hub.mode": "subscribe",
                    "hub.verify_token": token or "ac-domain-check-wrong-token",
                    "hub.challenge": echo,
                }
            )
            status, _, data = get(api, "GET", f"{path}?{query}")
            if token is None:  # the route answers, and refuses a wrong token
                return status == 403, f"{status}"
            return status == 200 and data.decode(errors="replace") == echo, f"{status}"

        return run

    def script() -> Result:
        status, headers, _ = get(app, "GET", "/sx.js")
        kind = headers.get("content-type", "")
        return status == 200 and "javascript" in kind, f"{status} {kind}"

    def forwards(host: str) -> Callable[[], Result]:
        def run() -> Result:
            status, headers, _ = get(host, "GET", "/leads?from=check")
            where = headers.get("location", "")
            return status == 302 and where == f"https://{app}/leads?from=check", f"{status} {where}"

        return run

    found += [
        ("page", page),
        ("mcp-metadata", resource),
        ("oauth-issuer", issuer),
        ("mcp-challenge", challenge),
        ("meta-webhook", webhook("/v1/lead-desk/meta/webhook", None)),
        ("whatsapp-webhook", webhook("/v1/lead-desk/meta/webhook/whatsapp", None)),
        ("website-line", script),
    ]
    if forward:
        found += [(f"forward-{host}", forwards(str(host))) for host in names["forward"]]  # type: ignore[union-attr]
        found += [(f"forward-{host}", forwards(host)) for host in sorted({api, mcp} - {app})]
    if not deep:
        return found

    key = os.environ.get("SX_CHECK_API_KEY")
    if key:
        bearer = {"Authorization": f"Bearer {key}"}

        def me() -> Result:
            status, _, _ = get(api, "GET", "/v1/api/me", headers=bearer)
            return status == 200, f"{status}"

        def tools() -> Result:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
            status, _, data = get(
                mcp,
                "POST",
                "/v1/mcp",
                headers={**bearer, "Content-Type": "application/json"},
                body=body,
            )
            listed = _json(data).get("result")
            return status == 200 and isinstance(listed, dict) and "tools" in listed, f"{status}"

        found += [("api-key", me), ("mcp-tools", tools)]
    for name, path, variable in (
        ("meta-handshake", "/v1/lead-desk/meta/webhook", "SX_CHECK_META_VERIFY_TOKEN"),
        (
            "whatsapp-handshake",
            "/v1/lead-desk/meta/webhook/whatsapp",
            "SX_CHECK_WHATSAPP_VERIFY_TOKEN",
        ),
    ):
        token = os.environ.get(variable)
        if token:
            found.append((name, webhook(path, token)))

    def google() -> Result:
        flow = quote(f"/auth/complete?flow={uuid4()}", safe="")
        status, headers, _ = get(
            app,
            "GET",
            f"/v1/auth/google/start?action=authenticate&surface=sales_xray&return_path={flow}",
        )
        where = headers.get("location", "")
        wanted = quote(f"https://{app}/v1/auth/google/callback", safe="")
        return status == 303 and f"redirect_uri={wanted}" in where, f"{status}"

    found.append(("google-redirect", google))
    return found


def run(args: argparse.Namespace) -> list[tuple[str, str, bool, str]]:
    get = Client(args.edge, args.timeout)
    results = []
    for family in args.family:
        for name, check in checks(family, get, deep=args.deep, forward=not args.no_forward):
            try:
                ok, detail = check()
            except (OSError, http.client.HTTPException) as error:
                ok, detail = False, type(error).__name__
            results.append((family, name, ok, detail))
    return results


def watch(directory: Path, results: list[tuple[str, str, bool, str]]) -> list[str]:
    """Count failures per check; the lines to raise (second failure in a row, then recovery)."""
    directory.mkdir(parents=True, exist_ok=True)
    state_file = directory / "state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    lines = []
    for family, name, ok, detail in results:
        key = f"{family}/{name}"
        entry = state.get(key, {"fails": 0, "alerted": False})
        if ok:
            if entry["alerted"]:
                lines.append(f"RECOVERED Sales X-Ray {key}")
            entry = {"fails": 0, "alerted": False}
        else:
            entry["fails"] += 1
            if entry["fails"] >= 2 and not entry["alerted"]:
                lines.append(
                    f"ALERT Sales X-Ray {key} failing ({entry['fails']} in a row): {detail}"
                )
                entry["alerted"] = True
        state[key] = entry
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary.replace(state_file)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--family", action="append", choices=sorted(FAMILIES))
    parser.add_argument("--edge", help="ask this edge (http://127.0.0.1:8080) with Host headers")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--no-forward", action="store_true", help="the landing site is live")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--watch", type=Path)
    parser.add_argument("--notify", help="command run with each ALERT/RECOVERED line")
    parser.add_argument("--until", help="YYYY-MM-DD (UTC): after it, do nothing")
    args = parser.parse_args(argv)
    args.family = args.family or ["old", "new"]
    if args.until and datetime.now(UTC).date().isoformat() > args.until:
        return 0
    results = run(args)
    for family, name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} {family:3} {name:20} {detail}")
    if args.watch is not None:
        for line in watch(args.watch, results):
            print(line)
            if args.notify:
                subprocess.run([args.notify, line], check=False, timeout=60)  # noqa: S603
    return 0 if all(ok for _, _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
