# Alpha private-file and authenticated runtime implementation

Status: implemented/tested seams, not VPS activation or final Alpha acceptance.
Implementation lane: existing `d2de` / `codex/local-staging-dev-bridge`.

## Read-only artifact storage

`media/file_storage.py` implements the private storage port using an explicit
immutable inventory. Every entry is SHA-256 and length checked before use.
Canonical inventory keys map only to safe relative files; arbitrary filesystem
discovery, traversal, symlinks and Windows reparse components are rejected.
Upload intent, put, copy and delete are unconditionally denied. Unknown object
keys cannot discover unlisted files.

Reads are bounded: small-body reads at most 1 MiB, prefix reads at most 1 MiB plus
one sentinel byte for existing HLS oversize detection; inclusive byte-range
streaming at most 16 MiB per chunk (1 MiB default). File identity is checked before
and after each read, and a consumer closing the generator closes the descriptor.
Registration limits are 8,192 objects, 8 GiB per object, 32 GiB total.

The deployment still must mount trusted artifacts read-only. Hash registration
and file identity checks are not a claim of security against an OS administrator
who can rewrite both artifacts and trusted metadata. Windows Python 3.12 exposes
different legacy `ctime` meanings through `lstat` and `fstat`; the implementation
uses their consistent explicit birth time on Windows and metadata-change time
on POSIX, alongside device/inode/size/mtime. The first test run detected this real
platform mismatch; it was corrected, not waived. Actual HLS integration then
identified the required sentinel-byte allowance, which was added with a focused
regression instead of weakening the playlist-size validator.

Focused verification: **59/59 tests passed**, including range boundaries, memory
caps, forbidden mutation, unlisted files, metadata/hash mismatch, link components,
replacement, deletion, truncation and mutation between chunks. Ruff and mypy
passed. An independent reviewer reran these alongside 37 activity-delivery tests:
**96 passed**, no actionable Critical/Important findings in those reviewed files.

## Application composition

The runtime now carries an optional per-request authenticated delivery factory.
It creates a fresh database authorizer for each actor/transaction. Delivery URL
signing and persisted grant-digest signing retain their correct separate signers.
Request-authenticated delivery must use the configured learner origin so host-only
session cookies are available. The application installs the authenticated GET/HEAD
router only when the explicit factory and exact-origin CORS policy are present.

Defaults remain unchanged: no file adapter, provider activation, signed delivery
router, injected staging/production runtime or canonical watch policy is enabled
by this change. Seven new composition tests pass; 89 existing app/provider tests
also pass. Actual non-production fixture activation requires the separate reviewed,
release/tenant/catalog/manifest-pinned import and runtime path being implemented.

## Prepared playback artifacts

The ignored `tools/media-player-stress/.artifacts/staging-alpha-public-films-12s-v1/`
pack contains two explicitly technical clips, not Dipak's instruction:

- `bbb-12s`: 3840x2160, 30 fps; HLS 2160p/1080p/360p.
- `caminandes-12s`: 1920x1080, 24 fps; HLS 1080p/360p.

Each progressive MP4 was remuxed from its same highest-quality HLS content using
FFmpeg 8.1.1 with file-only input protocols, stream copy and fast-start metadata.
The original full films were not substituted as fallback for short HLS clips.
Real ffprobe reports 12.000 seconds of video and 12.032 seconds of AAC/container
duration for each (32 ms of encoder padding). HLS playlists contain three 4-second
segments. Diagnostic captions are synthetic timing tests, not film transcripts.

| Artifact | SHA-256 |
| --- | --- |
| BBB progressive MP4 | `7e7ee255d0ca2866ad528e9d6ddc0049a66883d6984ea9bf4d9fed188907bd4a` |
| BBB probe JSON | `a4d219e7c5914da2067c53e203161b5af6033c0514cdf261c41fc2cd36c83f10` |
| Caminandes progressive MP4 | `a85f27d1b52848fb51c486a882e2bd61318da502b62d7537e81ecca739198d74` |
| Caminandes probe JSON | `d59aa2702bf85d0b657701545db314d4808c5b653ecf206cd2f00127b7da47e0` |

Source-film licenses, source-page evidence and original hashes remain in the
existing pinned fixture registry and second-media evidence. The new application
manifest is being built from actual files; this record is not a substitute for
that manifest, authorized import, actual HTTP playback, access-negative tests,
VPS resource measurements or production approval.
