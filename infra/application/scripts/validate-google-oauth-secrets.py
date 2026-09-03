#!/usr/bin/env python3
"""Fail closed when deployment Google OAuth credentials have no value."""

from __future__ import annotations

import os


def main() -> None:
    for variable_name in (
        "AC_GOOGLE_OAUTH_CLIENT_ID",
        "AC_GOOGLE_OAUTH_CLIENT_SECRET",
    ):
        if not os.environ.get(variable_name, "").strip():
            raise SystemExit(f"FAIL  {variable_name} must contain a non-whitespace value.")
    print("PASS  Google OAuth credential preflight accepted both required values.")


if __name__ == "__main__":
    main()
