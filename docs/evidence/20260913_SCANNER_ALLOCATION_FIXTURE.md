# Scanner allocation fixture under an unprivileged runner

CI34731858764 failed two synthetic allocation tests when an unprivileged Linux
runner tried to list a mode-000 directory. The production controller deliberately
uses that mode for its root-owned, unmounted scanner mountpoint and runs as root.
The allocation fixture already simulated ownership, mounts and image validation,
but had still applied the privileged directory permissions to real pytest files.

The fixture now simulates only the private mountpoint's privileged mkdir/chmod
operations, keeping the disposable test directory traversable. It records and
asserts the exact production permission requests: mode000 before a mount and
mode750 after it. Other paths use the real filesystem methods. The existing
allocation-once, retained interrupted image and old-debris refusal assertions
remain, and the production controller is unchanged.

Validation: all97 tests in `tests/infra/test_media_safety.py` passed on Windows;
Ruff lint/format and diff checks passed. The mandatory Linux CI loopback/ENOSPC
proof already passed at088058a; the corrected full CI suite must pass before
deployment. No runtime permission was relaxed and no host state changed.
