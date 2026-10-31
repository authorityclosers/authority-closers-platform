"""No real dispatches: exercise deploy pinning, retries, rollbacks and idempotence."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "infra/application/scripts/ac-staging-app-after-release"
)


class HookTests(unittest.TestCase):
    def test_dispatch_pin_retry_idempotence_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, gh = root / "release", root / "gh"
            release.write_text('#!/bin/sh\ncat "$FIXTURE/status"\n')
            gh.write_text('#!/bin/sh\necho "$*" >> "$FIXTURE/calls"\n[ ! -f "$FIXTURE/fail" ]\n')
            release.chmod(0o700)
            gh.chmod(0o700)
            env = {
                **os.environ,
                "FIXTURE": tmp,
                "AC_STAGING_APP_RELEASE": str(release),
                "AC_STAGING_APP_GH": str(gh),
                "AC_STAGING_APP_STATE": str(root / "state"),
                "AC_STAGING_APP_PAUSE": "0",
            }

            def status(sha):
                (root / "status").write_text(
                    json.dumps(
                        {
                            "environments": {
                                "staging": {"web": sha, "core": "c" * 40},
                                "production": {"web": "d" * 40},
                            }
                        }
                    )
                )

            def tick():
                return subprocess.run(  # noqa: S603 - fixed test argv, no shell
                    ["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
                )

            status("a" * 40)
            (root / "fail").touch()
            self.assertNotEqual(tick().returncode, 0)
            self.assertFalse((root / "state/last").exists())
            (root / "fail").unlink()
            self.assertEqual(tick().returncode, 0)
            count = len((root / "calls").read_text().splitlines())
            self.assertEqual(tick().returncode, 0)
            self.assertEqual(len((root / "calls").read_text().splitlines()), count)
            status("b" * 40)
            self.assertEqual(tick().returncode, 0)
            status("a" * 40)
            self.assertEqual(tick().returncode, 0)
            calls = (root / "calls").read_text()
            self.assertIn("staging-android.yml", calls)
            self.assertIn("web_ref=" + "a" * 40, calls)
            self.assertIn("web_ref=" + "b" * 40, calls)
            self.assertNotIn("c" * 40, calls)
            self.assertNotIn("d" * 40, calls)
            self.assertNotIn("play.yml", calls)
            status("main")
            self.assertNotEqual(tick().returncode, 0)
            self.assertEqual((root / "calls").read_text(), calls)


# A fake gh for the gate: run 100 is the newest before a dispatch and 101 after it; run 90
# still waits at its gate; the android-release environment is 777 and the new run's pending
# gate is FAKE_GATE (777 by default).
GATE_GH = """
import json, os, sys
here = os.environ["FIXTURE"]
args = sys.argv[1:]
with open(os.path.join(here, "calls"), "a") as log:
    log.write(json.dumps(args) + "\\n")
dispatched = os.path.join(here, "dispatched")
if args[:2] == ["workflow", "run"]:
    open(dispatched, "w").close()
elif args[:2] == ["run", "list"]:
    if "waiting" in args:
        print("90")
    else:
        print("101" if os.path.exists(dispatched) else "100")
elif args[0] == "api" and args[1].endswith("/environments/android-release"):
    print("777")
elif args[0] == "api" and args[1].endswith("/pending_deployments") and "-X" not in args:
    print(os.environ.get("FAKE_GATE", "777"))
"""


class GateTests(unittest.TestCase):
    """Owner, 31 Oct 2026: a staging QA build approves its own release gate, only its own."""

    def _tick(self, gate: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, gh = root / "release", root / "gh"
            release.write_text('#!/bin/sh\ncat "$FIXTURE/status"\n')
            gh.write_text(f"#!{sys.executable}\n{GATE_GH}")
            release.chmod(0o700)
            gh.chmod(0o700)
            envs = {"staging": {"web": "a" * 40}, "production": {"web": "d" * 40}}
            (root / "status").write_text(json.dumps({"environments": envs}))
            env = {
                **os.environ,
                "FIXTURE": tmp,
                "FAKE_GATE": gate,
                "AC_STAGING_APP_RELEASE": str(release),
                "AC_STAGING_APP_GH": str(gh),
                "AC_STAGING_APP_STATE": str(root / "state"),
                "AC_STAGING_APP_PAUSE": "0",
            }
            result = subprocess.run(  # noqa: S603 - fixed test argv, no shell
                ["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
            )
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
            return result, calls

    def test_its_own_run_is_approved_after_stale_waiting_runs_are_cancelled(self):
        result, calls = self._tick("777")
        self.assertEqual(result.returncode, 0, result.stderr)
        cancel = calls.index(["run", "cancel", "90", "-R", "authorityclosers/sales-xray-apps"])
        dispatch = next(i for i, c in enumerate(calls) if c[:2] == ["workflow", "run"])
        self.assertLess(cancel, dispatch)
        approvals = [c for c in calls if "-X" in c]
        self.assertEqual(len(approvals), 1)
        self.assertTrue(approvals[0][3].endswith("/actions/runs/101/pending_deployments"))
        self.assertIn("environment_ids[]=777", approvals[0])
        self.assertIn("state=approved", approvals[0])
        self.assertNotIn("play.yml", json.dumps(calls))

    def test_a_run_waiting_at_another_gate_is_not_approved(self):
        result, calls = self._tick("555")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse([c for c in calls if "-X" in c])
        self.assertIn("nothing approved", result.stdout)


if __name__ == "__main__":
    unittest.main()
