# Sales Xray report acceptance receipts

Runtime source: `63d5a5edd644bd250acdc8c51694712a3754c7f7`.

These are actual saved test outputs. The screenshots and PDF use a labelled
synthetic report. They are not the owner's WhatsApp recording or a deployed
provider-generated result.

- [67 passing UI tests](ui-vitest.xml)
- [Standalone optimized build](standalone-build.log)
- [Learner optimized build](learner-build.log)
- [Actual identity/HTTP/PostgreSQL/audio browser test](identity-audio-browser.junit.xml)
- [Its 14 checks and recorded network responses](identity-audio-browser.json)
- [Source, static export and runtime receipt](identity-audio-runtime.json)
- [Four-language UI, mobile and PDF receipt](ui-browser-receipt.json)
- [Synthetic report PDF](synthetic-synthetic-report.pdf)
- [Fresh anonymous live baseline](live-anonymous-baseline.json)
- [File sizes and SHA256 checksums](manifest.json)

The actual audio test opens a saved synthetic recording, uses the real AC
password session and workspace selection, plays/seeks the private WAV, reads
saved native C1 measurements, and confirms access is denied after logout. No
Google or provider call is performed. The UI recovery script separately uses
synthetic API responses and a substituted media play result to exercise failures.

The optimized build was served through `next start`; the Windows packaged-server
start failed at a traced dependency junction. Passing Linux image and live
authenticated staging/production tests remain release requirements. The live
baseline only checks public page availability and anonymous access denial.

Earlier failed attempts remain in the external audit locations named by the
parent evidence document. They are not counted as passing tests.
