"""No real dispatches: exercise deploy pinning, retries, rollbacks and idempotence."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'infra/application/scripts/ac-staging-app-after-release'


class HookTests(unittest.TestCase):
    def test_dispatch_pin_retry_idempotence_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, gh = root / 'release', root / 'gh'
            release.write_text('#!/bin/sh\ncat "$FIXTURE/status"\n')
            gh.write_text('#!/bin/sh\necho "$*" >> "$FIXTURE/calls"\n[ ! -f "$FIXTURE/fail" ]\n')
            release.chmod(0o700)
            gh.chmod(0o700)
            env = {**os.environ, 'FIXTURE': tmp, 'AC_STAGING_APP_RELEASE': str(release),
                   'AC_STAGING_APP_GH': str(gh), 'AC_STAGING_APP_STATE': str(root / 'state')}
            def status(sha):
                (root / 'status').write_text(json.dumps({'environments': {'staging': {'web': sha, 'core': 'c' * 40}, 'production': {'web': 'd' * 40}}}))
            def tick():
                return subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
            status('a' * 40)
            (root / 'fail').touch()
            self.assertNotEqual(tick().returncode, 0)
            self.assertFalse((root / 'state/last').exists())
            (root / 'fail').unlink()
            self.assertEqual(tick().returncode, 0)
            count = len((root / 'calls').read_text().splitlines())
            self.assertEqual(tick().returncode, 0)
            self.assertEqual(len((root / 'calls').read_text().splitlines()), count)
            status('b' * 40)
            self.assertEqual(tick().returncode, 0)
            status('a' * 40)
            self.assertEqual(tick().returncode, 0)
            calls = (root / 'calls').read_text()
            self.assertIn('staging-android.yml', calls)
            self.assertIn('web_ref=' + 'a' * 40, calls)
            self.assertIn('web_ref=' + 'b' * 40, calls)
            self.assertNotIn('c' * 40, calls)
            self.assertNotIn('d' * 40, calls)
            self.assertNotIn('play.yml', calls)
            status('main')
            self.assertNotEqual(tick().returncode, 0)
            self.assertEqual((root / 'calls').read_text(), calls)


if __name__ == '__main__':
    unittest.main()
