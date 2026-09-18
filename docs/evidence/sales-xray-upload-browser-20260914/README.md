# Fresh synthetic upload acceptance

Runtime source: `63d5a5edd644bd250acdc8c51694712a3754c7f7`.
Test overlays: `d55669168cd241375db9566152e52a68c3dddd06` and
`57a4743e252f04b2a8829597f011c88f5019723b`.

Actual Chromium, AC cookie-authenticated HTTP and disposable PostgreSQL:
**2 tests passed in 79.68 seconds**, eight recorded checks per test.

- [JUnit](sales-xray-report-browser.junit.xml)
- [Imported synthetic draft, fresh upload and native completion](authenticated-browser.json)
- [Synthetic durable report, fresh upload and native completion](durable-authenticated-browser.json)
- [Source, test overlays and static export checksum](source-runtime-receipt.json)
- [Exact receipt file hashes](manifest.json)

Each case records 23 API responses. Fresh WAV upload follows quote 201,
approval 200, private source upload 200 and queued run 202; a real local native
worker completes. Saved reports reopen without uploading again, and actual
authenticated audio range delivery returns 206. Zero external browser requests
or browser errors were observed.

The durable inference case uses a synthetic ReportingBroker. Its report is
test data. The fresh upload completes local measurements, which do not fabricate
a sales report. The minimal harness does not mount the further plan-quote route
(405 is recorded). No Google login, external inference, production runtime,
owner recording or hosted upload was tested. No provider network counter was
installed; provider execution is not configured in this harness.

The last overlay only updates the report-moment locator for the existing UI;
the subsequent actual audio seek assertion is retained. Earlier failed selector
attempts remain in the external audit directory and are not passing evidence.
