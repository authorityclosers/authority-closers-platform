#!/usr/bin/env python3
"""Run the ordinary member-owned recording importer against production as the AC organisation.

Owner order, 19 Oct 2026 (Suyash Kulkarni, chat): import Swamini's and Ankita's 64 Drive
recordings into the production Authority Closers organisation, each owned by its member,
and analyse them. This wraps recording_import_cli unchanged: preview (dry run) unless
--apply, member assignments, recording-rights confirmation, analysis plans, replay and
read-back. The owner session is injected as AC_RECORDING_IMPORT_COOKIE; it is never an
argument or printed here. Every request is pinned to the production edge on this host.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import httpx

from ac_platform.conversation_intelligence import recording_import_cli

EDGE = "http://127.0.0.1:8080"
HOST = "salesxray.authorityclosers.com"
ORIGIN = "https://salesxray.authorityclosers.com"
PREFIX = "/v1/conversation/acquisition/"
AC_ORGANISATION = "02150758-5316-46bb-975b-4cd0f0041df2"


class ProductionClient(httpx.Client):
    """Bind session-bearing requests to the production surface before transport."""

    def __init__(self, **kwargs: Any) -> None:
        if httpx.URL(kwargs.get("base_url", "")) != httpx.URL(EDGE):
            raise ValueError("Use the production edge on this host.")
        headers = httpx.Headers(kwargs.get("headers"))
        headers["Host"], headers["Origin"] = HOST, ORIGIN
        kwargs.update(headers=headers, trust_env=False, follow_redirects=False)
        super().__init__(**kwargs)

    def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        url = request.url
        if (
            url.scheme != "http"
            or url.host != "127.0.0.1"
            or url.port != 8080
            or url.userinfo
            or url.fragment
            or not url.path.startswith(PREFIX)
            or request.headers.get("Host") != HOST
            or request.headers.get("Origin") != ORIGIN
        ):
            raise ValueError("A production import request changed its destination or surface.")
        kwargs["follow_redirects"] = False
        return super().send(request, **kwargs)


def main() -> int:
    args = sys.argv[1:]
    if "--tenant-id" not in args or args[args.index("--tenant-id") + 1] != AC_ORGANISATION:
        raise SystemExit("Refused: --tenant-id must be the production Authority Closers organisation.")
    with patch.object(httpx, "Client", ProductionClient):
        return recording_import_cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
