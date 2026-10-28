"""The intake spool directories under a setgid application root (v1.1.0 staging, 27 Oct 2026).

`/srv/authority-closers/application` is setgid. GNU install and chmod keep a
directory's inherited setgid bit, so the spool root came out 2700 and the
installer's canonical-mode check stopped the staging release. The installer's
own function runs on temporary directories; only root ownership is simulated.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = (ROOT / "infra/application/scripts/install-application-release.sh").read_text()


def function(name: str) -> str:
    return name + "() {" + INSTALLER.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
@pytest.mark.parametrize("existing", [False, True])
def test_spool_root_is_canonical_under_a_setgid_application_root(
    tmp_path: Path, existing: bool
) -> None:
    application_root = tmp_path / "application"
    application_root.mkdir()
    application_root.chmod(0o2750)
    if not (application_root.stat().st_mode & stat.S_ISGID):
        pytest.skip("this filesystem does not keep the setgid bit")
    if existing:
        # Left by the failed v1.1.0 attempt: created inside the setgid parent.
        (application_root / "intake-spool" / "staging").mkdir(parents=True)
        (application_root / "intake-spool" / "staging").chmod(0o700)
    script = "set -euo pipefail\n" + function("prepare_intake_spool_root")
    script += r"""
application_root="$fixture/application"
intake_spool_root="$application_root/intake-spool/staging"
# Root ownership needs root; modes, setgid inheritance and checks are real.
install() {
  local -a kept=()
  while (($#)); do
    case "$1" in -o|-g) shift 2 ;; *) kept+=("$1"); shift ;; esac
  done
  command install "${kept[@]}"
}
stat() {
  if [[ "$2" == '%u:%g:%a' ]]; then
    printf '10001:10001:%s\n' "$(command stat -c %a "${@: -1}")"
  else
    command stat "$@"
  fi
}
prepare_intake_spool_root
"""
    result = subprocess.run(  # noqa: S603 - installer function on temporary directories only
        ["/bin/bash", "-c", script],
        env={**os.environ, "fixture": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    spool = application_root / "intake-spool"
    assert stat.S_IMODE((spool / "staging").stat().st_mode) == 0o700
    assert stat.S_IMODE(spool.stat().st_mode) == 0o750
    # The application root itself keeps its setgid bit.
    assert application_root.stat().st_mode & stat.S_ISGID
