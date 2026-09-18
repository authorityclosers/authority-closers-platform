# Persistent native supervision candidate

The native C1 image and helper already passed Release Recovery's actual VPS
two-run, wrong-image rejection and cleanup proof. This change reuses that frozen
artifact and adds source-owned persistent supervision around it. It does not
rebuild the image or perform a provider call.

`infra/application/scripts/render-sales-xray-native.py` renders two units per
environment: a 64 MiB private output mount and the native helper service. Only
versioned helper and application-script paths and an immutable image digest are
accepted. Rendering emits JSON and performs no installation. The helper process
receives a cleared environment, no provider identity directory access, a fixed
Unix socket, bounded resources and an 800-second stop/drain deadline. Docker
access remains on this helper, never in the API or database/provider worker.

The service preserves the socket directory used by the worker's bind mount.
Prestart refuses an active helper or an ambiguous/untrusted node; it removes only
a proven stale root-owned socket after an inode recheck. It never recursively
deletes a directory. The output mount has independent boot supervision.

## Evidence from this machine

- Focused tests: 28 passed in 1.54 seconds. Receipt:
  `D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/0033-native-supervisor-02.xml`.
- Tests cover both environments, exact source/image binding, injection and mutable
  reference rejection, render-only CLI behavior, stable socket-directory handling,
  stale/live sockets, ambiguous connection errors, inode replacement, foreign nodes
  and writable parent rejection. Linux socket/ownership branches use explicit
  mocks here; this is not a systemd execution receipt.
- Strict mypy passed for the renderer. Ruff lint and format checks passed for the
  renderer and focused tests; `git diff --check` passed.
- Initial receipt `0033-native-supervisor.xml` preserves six Windows test-harness
  failures from the host Python lacking `AF_UNIX`. The simulated Linux fixture now
  supplies that constant. Production behavior was not weakened to make tests pass.

## Reused VPS evidence and remaining execution

Native source: `6204dc48df72ec133d30ce32e24dbddf3ea4993d`.
Manifest: `sha256:fd29cbf1edc9f6b13ca9fcebc6903adee0fd70583c77b60bd1753816f7f57ef9`.
Separately verified config:
`sha256:75e3b01d100534ce667a97822ab34216b09553f820b60c2f66a223b72b481866`.
Actual host Python: `/usr/bin/python3`, version 3.12.3.
Release Recovery's native smoke receipt SHA256:
`2ff3aa8733f69cb3f280bb87fec4afaad0292784b9427b09706c420f759fa1f4`.

Docker29's containerd store reports the manifest as `.Id`; classic Docker reports
the bound configuration ID. The activation guide now documents both observed
store behaviors and preserves the archive/manifest/configuration binding.

The rendered supervisor still requires source-owned installation,
`systemd-analyze verify`, effective mount/unit inspection and actual supervised
restart/drain plus worker reconnection proof. Staging and production activation
are separate steps. No such installation or provider execution occurred here.
