#!/usr/bin/env python3
"""Install and prove CI codec, filesystem and locked browser prerequisites.

GitHub-hosted runners occasionally stall on apt mirror or browser CDN requests.
Every network operation here runs under a per-attempt time limit inside one
overall deadline, retries a bounded number of times and fails closed with a
short diagnostic. Packages that are already installed are not fetched again.
The browser comes from the Playwright package in the frozen uv environment that
runs this helper; its system libraries come from that same Playwright's own
dependency list, installed in one apt transaction with the codec tools.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

COMPONENTS = ("codec", "filesystem", "browser")
CODEC_PACKAGES = ("ffmpeg",)
CODEC_COMMANDS = ("ffmpeg", "ffprobe")
FILESYSTEM_PACKAGES = ("e2fsprogs", "util-linux")
FILESYSTEM_COMMANDS = ("mkfs.ext4", "losetup", "mount", "umount", "findmnt")
BROWSER = "chromium"

ATTEMPTS = 3
BACKOFF_SECONDS = (5, 15)
UPDATE_SECONDS = 120
INSTALL_SECONDS = 300
REPAIR_SECONDS = 120
DOWNLOAD_SECONDS = 240
PROBE_SECONDS = 60
KILL_GRACE_SECONDS = 10
DEADLINE_SECONDS = 720

APT_OPTIONS = (
    "-o",
    "Acquire::Retries=2",
    "-o",
    "Acquire::http::Timeout=20",
    "-o",
    "Acquire::https::Timeout=20",
    "-o",
    "DPkg::Lock::Timeout=60",
)
PLAYWRIGHT_ENV = {"PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT": "30000"}
DRY_RUN_PACKAGES = re.compile(r"apt-get install -y --no-install-recommends ([^\"\n]+)")
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9.+-]*$")
BROWSER_PROBE = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p:\n"
    "    b = p.chromium.launch()\n"
    "    page = b.new_page()\n"
    "    page.set_content('<p id=ok>ok</p>')\n"
    "    assert page.inner_text('#ok') == 'ok'\n"
    "    print('chromium', b.version)\n"
    "    b.close()\n"
)


class PrerequisiteError(RuntimeError):
    """A bounded diagnostic safe to print in CI logs."""


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    timed_out: bool = False


Runner = Callable[[Sequence[str], float, dict[str, str] | None], Result]


def run_bounded(argv: Sequence[str], seconds: float, env: dict[str, str] | None = None) -> Result:
    """Run one command in its own process group and kill the group on timeout."""
    merged = {**os.environ, **(env or {})}
    process = subprocess.Popen(  # noqa: S603 - fixed argv built by this helper
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=merged,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            try:
                output, _ = process.communicate(timeout=KILL_GRACE_SECONDS)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            output = ""
        return Result(returncode=124, stdout=output or "", timed_out=True)
    return Result(returncode=process.returncode, stdout=output or "")


@dataclass
class Prerequisites:
    runner: Runner = run_bounded
    which: Callable[[str], str | None] = shutil.which
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    python: str = sys.executable
    deadline_seconds: float = DEADLINE_SECONDS
    log: Callable[[str], None] = field(default=lambda line: print(line, flush=True))

    def __post_init__(self) -> None:
        self._deadline = self.clock() + self.deadline_seconds

    def _remaining(self, label: str) -> float:
        remaining = self._deadline - self.clock()
        if remaining <= 1:
            raise PrerequisiteError(f"{label}: overall {self.deadline_seconds:.0f}s budget spent")
        return remaining

    def _attempt(
        self,
        label: str,
        argv: Callable[[float], Sequence[str]],
        seconds: float,
        env: dict[str, str] | None = None,
        before_retry: Callable[[], None] | None = None,
    ) -> Result:
        last = Result(returncode=1)
        for attempt in range(1, ATTEMPTS + 1):
            limit = min(seconds, self._remaining(label))
            started = self.clock()
            last = self.runner(argv(limit), limit + KILL_GRACE_SECONDS * 2, env)
            took = self.clock() - started
            if last.returncode == 0 and not last.timed_out:
                self.log(f"{label}: ok on attempt {attempt} in {took:.0f}s")
                return last
            reason = "timed out" if last.timed_out else f"exit {last.returncode}"
            self.log(f"{label}: attempt {attempt}/{ATTEMPTS} {reason} after {took:.0f}s")
            tail = "\n".join(last.stdout.strip().splitlines()[-15:])
            if tail:
                self.log(tail)
            if attempt < ATTEMPTS:
                self.sleep(min(BACKOFF_SECONDS[attempt - 1], self._remaining(label)))
                if before_retry is not None:
                    before_retry()
        raise PrerequisiteError(f"{label}: failed after {ATTEMPTS} bounded attempts")

    def _sudo(self, seconds: float, *argv: str) -> list[str]:
        # timeout runs as root so it can kill apt/dpkg itself, not only sudo;
        # sudo resets the environment, so the frontend is set inside it.
        return [
            "sudo",
            "--non-interactive",
            "timeout",
            f"--kill-after={KILL_GRACE_SECONDS}s",
            f"{max(1, int(seconds))}s",
            "env",
            "DEBIAN_FRONTEND=noninteractive",
            *argv,
        ]

    def installed(self, package: str) -> bool:
        result = self.runner(
            ["dpkg-query", "--show", "--showformat=${db:Status-Status}", package], 30, None
        )
        return result.returncode == 0 and result.stdout.strip() == "installed"

    def browser_packages(self) -> list[str]:
        result = self.runner(
            [self.python, "-m", "playwright", "install-deps", "--dry-run", BROWSER],
            PROBE_SECONDS,
            None,
        )
        match = DRY_RUN_PACKAGES.search(result.stdout) if result.returncode == 0 else None
        packages = match.group(1).split() if match else []
        if not packages or not all(PACKAGE_NAME.fullmatch(name) for name in packages):
            raise PrerequisiteError("locked Playwright did not report its Chromium system packages")
        return packages

    def install_packages(self, packages: Sequence[str]) -> None:
        missing = [name for name in dict.fromkeys(packages) if not self.installed(name)]
        if not missing:
            self.log(f"apt: all {len(packages)} required packages already installed")
            return
        self.log(f"apt: installing {len(missing)} missing packages: {' '.join(missing)}")
        self._attempt(
            "apt-get update",
            lambda limit: self._sudo(limit, "apt-get", *APT_OPTIONS, "update"),
            UPDATE_SECONDS,
        )

        def repair() -> None:
            # A killed install can leave dpkg half-configured; finish it first.
            limit = min(REPAIR_SECONDS, self._remaining("dpkg repair"))
            self.runner(
                self._sudo(limit, "dpkg", "--configure", "-a"),
                limit + KILL_GRACE_SECONDS * 2,
                None,
            )

        self._attempt(
            "apt-get install",
            lambda limit: self._sudo(
                limit,
                "apt-get",
                *APT_OPTIONS,
                "install",
                "--yes",
                "--no-install-recommends",
                *missing,
            ),
            INSTALL_SECONDS,
            before_retry=repair,
        )
        still_missing = [name for name in missing if not self.installed(name)]
        if still_missing:
            raise PrerequisiteError(f"apt: still missing {' '.join(still_missing)}")

    def require_commands(self, commands: Sequence[str]) -> None:
        absent = [name for name in commands if self.which(name) is None]
        if absent:
            raise PrerequisiteError(f"required commands missing: {' '.join(absent)}")

    def prove_version(self, command: str) -> None:
        result = self.runner([command, "-version"], PROBE_SECONDS, None)
        if result.returncode != 0 or result.timed_out:
            raise PrerequisiteError(f"{command} -version failed")
        self.log(result.stdout.strip().splitlines()[0] if result.stdout.strip() else command)

    def install_browser(self) -> None:
        self._attempt(
            "playwright install",
            lambda _limit: [self.python, "-m", "playwright", "install", BROWSER],
            DOWNLOAD_SECONDS,
            env=PLAYWRIGHT_ENV,
        )

    def prove_browser(self) -> None:
        result = self.runner([self.python, "-c", BROWSER_PROBE], PROBE_SECONDS, None)
        if result.returncode != 0 or result.timed_out:
            tail = "\n".join(result.stdout.strip().splitlines()[-15:])
            if tail:
                self.log(tail)
            raise PrerequisiteError("locked Chromium did not launch headless")
        self.log(result.stdout.strip())

    def require(self, components: Sequence[str]) -> None:
        wanted = set(components)
        packages: list[str] = []
        if "codec" in wanted:
            packages += CODEC_PACKAGES
        if "filesystem" in wanted:
            packages += FILESYSTEM_PACKAGES
        if "browser" in wanted:
            packages += self.browser_packages()
        self.install_packages(packages)
        if "codec" in wanted:
            self.require_commands(CODEC_COMMANDS)
            for command in CODEC_COMMANDS:
                self.prove_version(command)
        if "filesystem" in wanted:
            self.require_commands(FILESYSTEM_COMMANDS)
        if "browser" in wanted:
            self.install_browser()
            self.prove_browser()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("components", nargs="+", choices=COMPONENTS)
    args = parser.parse_args(argv)
    try:
        Prerequisites().require(args.components)
    except PrerequisiteError as error:
        print(f"::error::CI prerequisites: {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
