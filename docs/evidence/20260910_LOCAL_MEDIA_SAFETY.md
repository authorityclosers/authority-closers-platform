# Local Studio video scanner pilot

The scanner is a separate, private VPS service for the isolated local upload acceptance path, not activation of uploads in staging or production. It does not alter WordPress, app routes, tenant data or payment/provider state. Official ClamAV 1.5.4 is pinned by digest; the non-root read-only container has 4 GiB RAM, two CPUs, bounded temporary storage/logs, and only a loopback port. Only signature databases persist.

The controller consumes an exact checksum-verified Git archive, retains immutable release files, and refuses implicit replacement of another scanner release. Readiness validates container bounds, mounted configuration, updater policy, live identity and clean/EICAR probes. It requires daily signatures no older than 48 hours and emits a 12-hour proof for the exact local SSH endpoint. This is not a guarantee against all malware.

Before packaging: 30 independent offline scanner tests passed; 10 launcher tests passed separately, including actual PowerShell opt-in evaluation. Independent review cleared the bounded scanner/controller/launcher changes after correcting writable signature storage and updater-policy validation. Real scanner activation, live signature verification and browser upload-to-playback are subsequent acceptance gates; these test results do not claim them completed.

Source references: [official Docker operation guidance](https://docs.clamav.net/manual/Installing/Docker.html), [ClamAV 1.5.4 security release](https://blog.clamav.net/2026/08/clamav-154-and-146-security-patch.html). The local upload pilot remains capped at 100 MiB source bytes and 8 GiB private storage; a short 4K fixture does not prove long-lecture acceptance.
