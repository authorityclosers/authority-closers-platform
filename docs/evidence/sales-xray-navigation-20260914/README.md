# Report navigation test receipts

Runtime source: `cb886effe8f6d21c5fbe1e645d625adeca4d3107`.

- [70 UI tests](ui-tests.junit.xml)
- [Standalone build](standalone-build.log) and [learner build](learner-build.log)
- [Three actual local browser tests](browser.junit.xml)
- [Identity, private audio and measurements](identity-browser.json)
- [Fresh upload and native completion](upload-browser.json)
- [Synthetic durable report and fresh upload](durable-report-browser.json)
- [Actual browser runtime and export checksum](auth-runtime.json)
- [Production-build fixture UI browser](ui-browser.json)
- [Synthetic report PDF](synthetic-report.pdf) and [PDF checks](pdf-inspection.json)
- [Reused native binary verification](native-reuse.json)
- [Live anonymous availability only](live-anonymous-baseline.json)
- [Receipt checksums](manifest.json)

Screenshots and PDF contain synthetic data. The UI browser uses fixture API
responses; the three separate identity/upload tests use real AC HTTP and
PostgreSQL with synthetic recordings. Neither proves an external provider run
or staging/production upload. The saved image named measurements in the external
identity harness captures the selected Transcript tab after its earlier sound
assertions; the network and assertions, rather than that filename, are the
measurement evidence. Earlier failed attempts are preserved in the parent report.
