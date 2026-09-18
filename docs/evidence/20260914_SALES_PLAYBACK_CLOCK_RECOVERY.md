# Sales Xray playback clock regression

Application CI run `34795053984` at source `30cd7a8d1aed95e8ead2ee737c9cfa6574d4d599` passed 5,402 tests and failed two report-browser journeys. Both failed the shared assertion that `audio.currentTime` must equal zero immediately after clicking a report moment starts playback. The observed positions were 0.015884 and 0.001021 seconds.

The proof now pauses and seeks the real audio element to 0.5 seconds, waits for that seek to finish, and slows playback to 0.1x before clicking the actual report moment. It requires playback to start and the position to return within 0.05 seconds of the beginning. Continuing from the previous position still fails. The authenticated source URL, range response, report rendering and access checks remain intact.

This changes the browser proof only. It does not change application playback, provider execution or release policy. Ruff lint passes; the file is formatted with the repository's pinned formatter. Independent Luna review and both affected Chromium journeys passed against the rebuilt static export and disposable PostgreSQL: **2 passed in 95.08 seconds**, with no mocked API routes, provider calls, external requests or browser errors.

JUnit evidence: `D:/AC-authority-closers-release-audit/activation-20260914/browser-fix-proof-20260914/browser.junit.xml`, SHA-256 `83197378d6194407ed121871ce32436dda99bed1c32ce5757ae07b1b2a72aee9`. This is local validation; hosted release evidence remains separate.
