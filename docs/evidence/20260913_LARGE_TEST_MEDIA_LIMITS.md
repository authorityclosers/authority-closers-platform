# Large licensed test media source limits — 2026-09-13

This source-only slice raises the authenticated Coach Studio video pipeline's
bounded source ceiling so the already verified Big Buck Bunny 4K test fixture
can pass the same upload, scanner, FFmpeg worker, catalog binding and private
delivery lifecycle. It does not copy the ignored fixture, activate a provider,
change production state, or publish the test film as course content.

The exact source ceiling is **2,000,000,000 bytes** (decimal). The application
settings, media configuration, ClamAV admission config, scanner readiness proof,
filesystem byte transport, request body guard and Coach capability all use this
same value. Coach displays the decimal value as `2.0 GB`; it does not silently
describe a binary 2 GiB allowance. The scanner's aggregate scan bound is
4,000,000,000 bytes and its bounded total scan timeout is 1,800 seconds.

The private filesystem store remains capped at **8 GiB** (`8 * 1024**3`) with
the existing object-count and atomic inventory guards. The scanner remains a
non-root, read-only ClamAV container limited to **2 CPUs**, **4 GiB RAM**, and
the existing 256 MiB scanner tmpfs. The application worker remains bounded by
the existing deployment profile at **1 CPU** and **512 MiB RAM**; FFmpeg's
existing processing quota and temporary workspace reservations remain in force.

## Verified fixture receipt

- Fixture: `bbb-4k-30-normal`
- License: Creative Commons Attribution 3.0
- Source bytes: `633016449`
- Source SHA-256: `37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520`
- Video: H.264, 3840×2160, 30/1 fps
- Duration: 634.600000 seconds container duration (10m 34.6s)
- Authoritative local path: `tools/media-player-stress/.artifacts/sources/bbb-4k-30-normal/bbb_sunflower_2160p_30fps_normal.mp4`

The binary remains in the ignored AC-owned media cache. The checked-in fixture
manifest and prior verification record provide the provenance and checksum.

## Operator activation boundary

The reviewed local/test composition is opt-in and still fail-closed until the
managed scanner proof is current. Root may run the existing isolated launcher
after placing the proof and verified fixture cache in the AC-owned workspace:

```powershell
pwsh -File scripts/Start-LocalStudioVideoScanner.ps1 `
  -ReleaseSha <reviewed-scanner-release-sha> `
  -ArchiveSha256 <reviewed-scanner-archive-sha256>
pwsh -File scripts/Start-LocalPlatform.ps1 -StudioVideo
```

This command is an operator instruction only; this task did not run it, upload
the film, mutate a database, or contact a provider. Production deployment still
requires the separately controlled scanner/storage/delivery activation and root
release process.
