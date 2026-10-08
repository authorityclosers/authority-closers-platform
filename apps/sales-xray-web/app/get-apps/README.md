# Companion downloads

The server reads `latest.json` and artifacts from
`SALES_XRAY_COMPANION_DOWNLOADS_DIR`. There is no default directory. Unset,
blank, missing or invalid manifests show “Not available yet”. No builds are
published by this page.

Card 20's manifest contract is `{ "version": "0.1.0", "files": [...] }`.
Each file has `name`, `platform` (`android`, `ios`, `windows`, `macos` or
`chrome`), positive integer `size` in bytes, and a 64-character hex `sha256`.
Extra publisher provenance fields are permitted. Filenames use ASCII letters,
digits, dots, underscores and hyphens, start with a letter or digit, are at
most 180 characters, and contain no `..`. `latest.json` is never downloadable.
Duplicate names invalidate the manifest. Downloads refuse symlinks and files
whose size differs from the manifest. The displayed hash comes from the manifest;
the publisher must calculate it from the artifact before publication.

Both the page and the download handler check the canonical `/v1/me/workspaces`
API at the configured `AC_CONVERSATION_API_ORIGIN`, with no caching or redirects.
No cookie or a rejected session prevents access; API failures fail closed.
