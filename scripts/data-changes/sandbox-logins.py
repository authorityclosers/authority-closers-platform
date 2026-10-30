"""The sandbox sellers' passwords: made once, kept only in Infisical, and turned into the
scrypt verifiers sandbox-organisations.py stores (owner chat 30 Oct 2026; AGENTS.md,
OWNER-APPROVED SECRETS).

Run where the Infisical CLI is signed in with write access (the operator's laptop: ac's
machine identity only reads), once per environment:
    python scripts/data-changes/sandbox-logins.py --env prod --out <verifiers.json> <email> ...
Each email gets a secret named SANDBOX_LOGIN_<ALIAS> (``admin+ac.priya@…`` is
SANDBOX_LOGIN_AC_PRIYA) in the environment's ``/sandbox-logins`` folder. A password already
there is kept and read back only to make its verifier; a missing one is made (24 random
URL-safe characters) and set from a private temporary file, never through the command line.
Nothing here prints a password or a verifier: the verifiers go to ``--out`` (mode 0600),
which the operator passes on as the generator's ``password_hashes`` and then deletes.
Staging and production keep their own passwords; dev has its own too.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path
from typing import Final

PROJECT: Final = "b421c44e-4599-4394-8df6-758ed8aedfed"
FOLDER: Final = "sandbox-logins"
ENVIRONMENTS: Final = ("dev", "staging", "prod")


def secret_name(email: str) -> str:
    """SANDBOX_LOGIN_<ALIAS> for a plus-alias sign-in email."""
    local = email.strip().lower().split("@", 1)[0]
    if "+" not in local:
        raise SystemExit(json.dumps({"refused": "not_a_plus_alias", "email": email}))
    alias = re.sub(r"[^A-Z0-9]+", "_", local.split("+", 1)[1].upper()).strip("_")
    return f"SANDBOX_LOGIN_{alias}"


def verifier(password: str, salt: bytes | None = None) -> str:
    """The app's own password verifier (identity.password_auth.hash_password), from the
    standard library only, so the laptop needs nothing else."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 2**20
    )

    def text(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return f"scrypt$ln=15,r=8,p=1${text(salt)}${text(digest)}"


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed program, arguments built here
        ["infisical", *args, f"--projectId={PROJECT}"],  # noqa: S607
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "INFISICAL_DISABLE_UPDATE_CHECK": "true"},
    )


def _existing(env: str, name: str) -> str | None:
    found = _cli("secrets", "get", name, f"--env={env}", f"--path=/{FOLDER}", "--plain", "--silent")
    value = found.stdout.strip()
    return value if found.returncode == 0 and value else None


def _set(env: str, name: str, password: str) -> None:
    with tempfile.TemporaryDirectory() as private:
        path = Path(private) / "value"
        path.write_text(password, encoding="utf-8")
        path.chmod(0o600)
        done = _cli("secrets", "set", f"{name}=@{path}", f"--env={env}", f"--path=/{FOLDER}")
        path.write_text("x" * len(password), encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(json.dumps({"refused": "infisical_set_failed", "secret": name}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("emails", nargs="+")
    given = parser.parse_args()
    _cli("secrets", "folders", "create", f"--name={FOLDER}", "--path=/", f"--env={given.env}")
    verifiers: dict[str, str] = {}
    report: dict[str, str] = {}
    for email in given.emails:
        name = secret_name(email)
        password = _existing(given.env, name)
        if password is None:
            password = secrets.token_urlsafe(18)
            _set(given.env, name, password)
            if _existing(given.env, name) != password:
                refused = {"refused": "infisical_read_back_differs", "secret": name}
                raise SystemExit(json.dumps(refused))
            report[name] = "made"
        else:
            report[name] = "kept"
        verifiers[email.strip().lower()] = verifier(password)
    given.out.write_text(json.dumps(verifiers), encoding="utf-8")
    given.out.chmod(0o600)
    print(json.dumps({"environment": given.env, "folder": f"/{FOLDER}", "secrets": report}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
