# Scanner endpoint validation across Python patch versions

Application CI run `34713937665` failed
`test_rejects_unsafe_endpoints_and_unbounded_settings[change5]` with
`DID NOT RAISE ValueError`. The exact input was `::ffff:127.0.0.1`; the runner
used Linux Python 3.12.14. The retained external log is
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery/pr56-ci-failure-34713937665.log`.

This is an IP classification difference, not DNS resolution. The local Windows
venv uses Python 3.12.0, whose `IPv6Address.is_loopback` accepts only the native
IPv6 loopback address. Python 3.12.14 delegates this classification to the
embedded IPv4 address for IPv4-mapped IPv6 values. See the pinned
[CPython implementation](https://github.com/python/cpython/blob/v3.12.14/Lib/ipaddress.py#L1995).
The scanner relied on the older classification to reject mapped addresses,
although its existing test already required that rejection.

`ClamAVScannerConfig` now explicitly rejects every IPv4-mapped IPv6 endpoint.
Literal native IPv4 loopback addresses and native IPv6 loopback remain accepted;
hostnames, remote addresses, scoped IPv6, ambiguous endpoints and unbounded
settings remain rejected. Connections still use the selected address family
and literal address without a DNS lookup. No deployment, daemon configuration,
signature, readiness, scan-size or provider policy changed.

Three new regression cases exercise mapped dotted-decimal, compressed hexadecimal
and expanded hexadecimal forms. They install the newer stdlib classification
behavior during the test so Python 3.12.0 can reproduce the defect. All three
failed before the implementation fix and pass afterward. Additional coverage
rejects scoped native IPv6 and verifies literal transport for another native
IPv4 loopback address and expanded native IPv6 loopback.

Validation on Windows / Python 3.12.0:

- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/unit/media/test_clamav_scanner.py`:
  **94 passed in 2.30 seconds**. This includes the existing bounded loopback
  protocol peer; it is not a live ClamAV antivirus acceptance proof.
- Targeted Ruff lint and format checks passed for the scanner and its unit file.
- The regression reproduces the relevant newer stdlib behavior locally; an
  actual Linux CI rerun remains required. Other failures in the original CI run
  are separate repairs and are not cleared by this scanner result.

Only the scanner adapter, its unit tests and this evidence file belong to this
repair. No heavy tests, browser work, external provider calls, DB operations,
Git staging, commits or publishing were performed by this repair task.
