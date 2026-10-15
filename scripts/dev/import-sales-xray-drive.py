#!/usr/bin/env python3
"""Run the ordinary Drive recording importer against the exact shared dev API.

Uses recording_import_cli's existing flags, dry-run, member assignments,
consent, analysis plans, replay and progress. The current dev session is injected
as AC_RECORDING_IMPORT_COOKIE; it is never an argument or printed here.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx

from ac_platform.conversation_intelligence import recording_import_cli

LIVE = "http://127.0.0.1:8101"
HOST = "salesxray-dev.authorityclosers.com"
ORIGIN = "https://salesxray-dev.authorityclosers.com"
PREFIX = "/v1/conversation/acquisition/"


class DevClient(httpx.Client):
    """Bind session-bearing requests to the current dev surface before transport."""

    def __init__(self, **kwargs: Any) -> None:
        if httpx.URL(kwargs.get("base_url", "")) != httpx.URL(LIVE):
            raise ValueError("Use the exact shared dev API origin.")
        headers = httpx.Headers(kwargs.get("headers"))
        headers["Host"], headers["Origin"] = HOST, ORIGIN
        kwargs.update(headers=headers, trust_env=False, follow_redirects=False)
        super().__init__(**kwargs)

    def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        url = request.url
        if (
            url.scheme != "http"
            or url.host != "127.0.0.1"
            or url.port != 8101
            or url.userinfo
            or url.fragment
            or not url.path.startswith(PREFIX)
            or request.headers.get("Host") != HOST
            or request.headers.get("Origin") != ORIGIN
        ):
            raise ValueError("A dev import request changed its destination or surface.")
        kwargs["follow_redirects"] = False
        return super().send(request, **kwargs)


def main() -> int:
    # Keep the existing operator's authority and state handling. The patch is
    # process-local and always restored, including on refusal or interruption.
    with patch.object(httpx, "Client", DevClient):
        return recording_import_cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
