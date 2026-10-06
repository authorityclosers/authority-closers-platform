#!/usr/bin/env python3
"""Root-only runner for existing released dev QA tools; fixture preview is the default.

No image build/pull, persistent container, service edit or credential file.
Infisical injects dev /application into root; only named dev inputs reach the
non-root released executable. Authority remains on AUT-959, outside this tool.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import urlsplit

RELEASE = "b5e240d29d7a24e7c81d3183665fd88a9e144899"
RELEASE_DIR = Path("/srv/authority-closers/application/releases") / RELEASE
DATABASE_CONTAINER = "acdev-postgres"
DATABASE_NETWORK = "acdev-xray"
DATABASE_IP = "172.27.0.2"
OPERATIONS_EMAIL = "qa-dev-operations-owner-aut959@example.test"
SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
INPUTS = (
    "AC_DATABASE_URL",
    "AC_SESSION_TOKEN_PEPPER",
    "AC_EMAIL_CHALLENGE_SECRET",
    "AC_LEARNER_CONSENT_VERSION",
    "AC_PUBLIC_LEARNER_TENANT_ID",
    "AC_OPERATIONS_TENANT_ID",
    "AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF",
    "AC_DEV_BILLING_FIXTURE_PASSWORD_CUSTOMER",
    "AC_BILLING_FAKE_PROVIDER_SIGNING_KEY",
)
MODULES = {
    "fixture": "ac_platform.development.billing_qa_fixture",
    "owner": "ac_platform.authorization.operator_data_change",
    "first-manager": "ac_platform.authorization",
}
MODULE_SHA256 = {
    "ac_platform.development.billing_qa_fixture": (
        "8328ff61345b094be96acc8eaae685eeb3caa0e4a530fc97df3b1a63b7cb4a74"
    ),
    "ac_platform.authorization.operator_data_change": (
        "96f585fb7a1489388835f71e56930870aa2666bdbc4918ae52e2829256e254d3"
    ),
    "ac_platform.authorization.__main__": (
        "4e264d8135dadcc2d00eabbc91e7e091335f778875261ed3e3e6516f9248eeb1"
    ),
}
PROBE = (
    "import hashlib,importlib.util,os,socket; from pathlib import Path; "
    "from ac_platform.development.billing_qa_fixture import EMAILS,PASSWORD_VARIABLES; "
    f"assert Path('/app/.ac-release-id').read_text().strip()=={RELEASE!r}; "
    "assert os.getuid()==10001; "
    f"assert {{r[4][0] for r in socket.getaddrinfo({DATABASE_CONTAINER!r},5432,"
    f"socket.AF_UNSPEC,socket.SOCK_STREAM)}}=={{{DATABASE_IP!r}}}; "
    f"assert all(hashlib.sha256(Path(importlib.util.find_spec(m).origin).read_bytes())"
    f".hexdigest()==h for m,h in {MODULE_SHA256!r}.items()); "
    "assert EMAILS['staff']=='qa-billing-staff-aut969@example.test'; "
    "assert PASSWORD_VARIABLES['staff']=='AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF'; "
    "print('released_dev_qa_contract_ok')"
)
TARGET_CHECK = """
import os,sys,runpy
from ac_platform.application.settings import Settings
from ac_platform.development.billing_qa_fixture import require_target
try:
    require_target(Settings(_env_file=None), os.environ)
except Exception:
    print('dev_qa_target_refused', file=sys.stderr)
    sys.exit(2)
"""
INVENTORY = """
import json
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession,create_async_engine
from ac_platform.application.asyncio_runtime import run_async
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.identity.models import Person
async def inventory():
    engine=create_async_engine(Settings(_env_file=None).database_url,hide_parameters=True)
    try:
        async with engine.connect() as connection:
            connection=await connection.execution_options(
                isolation_level='REPEATABLE READ',postgresql_readonly=True)
            async with connection.begin():
                async with AsyncSession(bind=connection) as database:
                    count=await database.scalar(select(func.count()).select_from(CapabilityGrant))
                    people=list(await database.scalars(select(Person.id).where(
                        func.lower(Person.email)=='qa-dev-operations-owner-aut959@example.test')))
                    print(json.dumps({'transaction_readonly':True,'grant_history_count':count,
                        'operations_person_ids':[str(p) for p in people]},sort_keys=True))
    finally:
        await engine.dispose()
run_async(inventory())
"""


class RunnerRefused(RuntimeError):
    pass


def require(ok: bool) -> None:
    if not ok:
        raise RunnerRefused


def metadata(argv: list[str], *, runner=subprocess.run) -> str:
    result = runner(  # noqa: S603 - fixed metadata commands, never a shell
        argv, env=SAFE_ENV, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30
    )
    require(result.returncode == 0)
    return result.stdout.decode().strip()


def runtime(release_dir: Path = RELEASE_DIR, *, runner=subprocess.run) -> list[str]:
    require(release_dir.is_dir() and not release_dir.is_symlink())
    require(release_dir.stat().st_uid == 0 and not release_dir.stat().st_mode & 0o022)
    require(
        metadata(
            ["sha256sum", "--check", "--strict", "--quiet", "RELEASE-FILES.sha256"],
            runner=lambda argv, **kw: runner(argv, cwd=release_dir, **kw),
        )
        == ""
    )
    values = dict(
        line.split("=", 1) for line in (release_dir / "release-images.env").read_text().splitlines()
    )
    require(values.get("AC_RELEASE_ID") == RELEASE)
    image = values.get("AC_API_IMAGE", "")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None)
    fmt = '{{.Id}}|{{index .Config.Labels "org.opencontainers.image.revision"}}'
    config_id, label = metadata(
        ["docker", "image", "inspect", "--format", fmt, image], runner=runner
    ).split("|", 1)
    require(config_id == image and label == RELEASE)
    networks = json.loads(
        metadata(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .NetworkSettings.Networks}}",
                DATABASE_CONTAINER,
            ],
            runner=runner,
        )
    )
    require(isinstance(networks, dict))
    endpoint = networks.get(DATABASE_NETWORK)
    require(isinstance(endpoint, dict) and endpoint.get("IPAddress") == DATABASE_IP)
    # Other attachments are allowed only when they cannot also identify the
    # approved endpoint. Selection is by the reviewed network name, never order.
    require(all(isinstance(value, dict) for value in networks.values()))
    require(sum(value.get("IPAddress") == DATABASE_IP for value in networks.values()) == 1)
    require(
        metadata(
            ["docker", "network", "inspect", "--format", "{{.Driver}}", DATABASE_NETWORK],
            runner=runner,
        )
        == "bridge"
    )
    return [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--read-only",
        "--user=10001:10001",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
        "--cpus=0.25",
        "--memory=256m",
        "--memory-swap=256m",
        "--log-driver=none",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001",
        "--network",
        DATABASE_NETWORK,
        "--entrypoint=/app/.venv/bin/python",
        image,
    ]


def injected_environment(environ: dict[str, str]) -> dict[str, str]:
    require(environ.get("AC_INFISICAL_ENVIRONMENT") == "dev")
    require(environ.get("AC_INFISICAL_PATH") == "/application")
    require(environ.get("AC_ENVIRONMENT") == "development")
    require(environ.get("AC_BILLING_ALLOW_LIVE", "false").lower() in {"false", "0"})
    require(not any(name.upper().startswith("PG") for name in environ))
    require(
        not any(
            environ.get(name)
            for name in (
                "AC_RAZORPAY_KEY_ID",
                "AC_RAZORPAY_KEY_SECRET",
                "AC_RAZORPAY_WEBHOOK_SECRET",
            )
        )
    )
    require(all(environ.get(name) for name in INPUTS[:6]))
    parsed = urlsplit(environ["AC_DATABASE_URL"])
    require(
        parsed.scheme == "postgresql+psycopg"
        and parsed.username == "ac_runtime"
        and parsed.hostname in {DATABASE_CONTAINER, DATABASE_IP}
        and (parsed.port or 5432) == 5432
        and parsed.path == "/ac_platform"
        and not parsed.query
        and not parsed.fragment
    )
    selected = {name: environ[name] for name in INPUTS if environ.get(name)}
    # Only routing changes, after the Docker endpoint and DNS probe identify the
    # same database. The fixture's exact acdev-postgres guard still runs inside.
    authority = parsed.netloc.rsplit("@", 1)[0]
    selected["AC_DATABASE_URL"] = parsed._replace(
        netloc=f"{authority}@acdev-postgres:5432"
    ).geturl()
    return {
        **SAFE_ENV,
        **selected,
        "AC_ENVIRONMENT": "development",
        "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "true",
        "AC_BILLING_ALLOW_LIVE": "false",
    }


def command(tool: str, args: list[str]) -> list[str]:
    require(tool != "preflight" or not args)
    require(tool != "inventory" or not args)
    if tool in {"owner", "first-manager"}:
        flag = "--email" if tool == "owner" else "--expected-email"
        require(
            all(not arg.startswith(("--email", "--expected-email")) or arg == flag for arg in args)
        )
        require(args.count(flag) == 1)
        value_index = args.index(flag) + 1
        require(value_index < len(args) and args[value_index] == OPERATIONS_EMAIL)
        args = ["add-operations-owner" if tool == "owner" else tool, *args]
    return args


def main(argv: list[str] | None = None, *, runner=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "tool", choices=("preflight", "inventory", *MODULES), nargs="?", default="fixture"
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    try:
        require(os.geteuid() == 0)
        parsed = parser.parse_args(argv)
        args = command(parsed.tool, parsed.args)
        base = runtime(runner=runner)
        base[2:2] = ["--name", f"ac-dev-billing-qa-{parsed.tool}-{os.getpid()}"]
        # No injected values are given to the artifact/DNS/UID probe.
        probe = runner(
            [*base, "-c", PROBE],
            env=SAFE_ENV,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            check=False,
        )  # noqa: S603
        require(probe.returncode == 0)
        if parsed.tool == "preflight":
            print(
                json.dumps(
                    {
                        "ok": True,
                        "release": RELEASE,
                        "image": base[-1],
                        "network": base[-3],
                        "database_container": DATABASE_CONTAINER,
                        "database_ip": DATABASE_IP,
                        "module_sha256": MODULE_SHA256,
                        "uid": 10001,
                    },
                    sort_keys=True,
                )
            )
            return 0
        env = injected_environment(dict(os.environ))
        flags = [flag for name in env if name.startswith("AC_") for flag in ("--env", name)]
        execution = (
            INVENTORY
            if parsed.tool == "inventory"
            else (
                f"sys.argv={[MODULES[parsed.tool], *args]!r}; "
                f"runpy.run_module({MODULES[parsed.tool]!r},run_name='__main__')"
            )
        )
        script = (
            TARGET_CHECK
            + "\ntry:\n"
            + textwrap.indent(execution, "    ")
            + (
                "\nexcept Exception:\n"
                "    print('dev_qa_command_refused', file=sys.stderr)\n"
                "    sys.exit(2)\n"
            )
        )
        result = runner(
            [*base[:-1], *flags, base[-1], "-c", script],
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=180,
        )  # noqa: S603
        return result.returncode
    except (Exception, KeyboardInterrupt):
        print(
            "dev-billing-qa: refused; verify released artifact, dev target and named inputs",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
