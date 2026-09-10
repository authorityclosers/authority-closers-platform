# Studio upload transfer repair — local candidate

Status: local source repair, not a staging/production deployment or successful
browser upload-to-preview proof. Existing saved content and credentials are
unchanged. The three local app login routes and API readiness were reverified
after a sequential managed startup on 2026-09-11.

## Failure and repair

The retained real-browser proof at
`.tmp/local-platform/new/studio-video-preview/20260910T135347505604Z/proof.json`
shows normal Coach login and upload admission, followed by HTTP 413 on the
14,538,778-byte licensed BBB fixture. The matching Coach server warning reports
Next.js truncation at its default 10 MiB proxy body-clone limit.

In pinned Next 16.2.11, the middleware matcher runs before `runMiddleware`, whose
body clone buffers and truncates the incoming stream. Coach already returned
`NextResponse.next()` for every `/v1/` request. Its matcher now excludes only the
raw `/v1/admin/studio/programs/{id}/video-uploads/{id}/bytes` shape before cloning.
Other API routes and page authentication remain unchanged. Actual authorization
still belongs to the fixed Coach route, exact local-origin/UUID/method/header
checks, session resolution and tenant/course permission checks at the API.

The native local upload transport also no longer treats a browser stream's
chunk boundary as an application size limit. A valid incoming chunk is divided
into at most 1 MiB views and each native write callback is awaited before the
next slice or source pull. Declared total size, length mismatch, deadlines,
concurrency, cancellation and early upstream rejection remain enforced. Neither
the normal 1 MiB JSON limit nor the scanner's 100 MiB source limit was raised.

Reference: [Next.js proxy body buffering](https://nextjs.org/docs/app/api-reference/config/next-config-js/proxyClientMaxBodySize).
The installed 16.2.11 implementation was inspected directly; current online
documentation is not used as proof of a different installed version.

## Verification

- Coach matcher: 24 tests passed using Next's actual pinned matcher compiler,
  including path near-misses, retained asset exclusions and production page
  login/capability gates. Coach TypeScript passed.
- Native upload transport: 46 tests passed; Admin TypeScript passed. Tests
  include real HTTP transfer, oversized incoming chunks, exact bounded writes,
  abort during splitting, early permission denial and length mismatch.
- An independent review found no Critical/Important production-code defect but
  requested deterministic backpressure evidence. That test now withholds the
  first native write callback, proves only one write/source pull occurred,
  releases it, then verifies `[1 MiB, 1 MiB, 17 bytes]` and the exact receipt.
  Root inspected this correction. The focused suite passed again.
- Independent matcher review: CLEAR, no Critical/Important findings.

## Remaining acceptance, not waived

The private scanner still runs the retained legacy release
`3eb24da05caced66f15dcfe58ffc086014da8b0d` with Docker health `unhealthy`.
Read-only SSH verified the documented IPv4 PING/PONG discrepancy. Its retained
archive SHA-256 is
`f4ed561104193502ee01a62b48109dcc5b1eb2850ed23bb55d5fc96c63eb143f`.
There is no local scanner forward on port 13310. No legacy readiness proof was
minted to bypass the corrected health gate.

The corrected scanner controller must be packaged and transitioned by exact
immutable release identity, then pass Docker health and functional probes.
Only after that can the opted-in local upload-to-processing-to-private-preview
browser proof resume. The ordinary local apps remain available with Studio
upload disabled. Full-length 4K, 1–2 GiB uploads, captions and deployed upload
support are separate unfinished requirements. No WordPress, DNS, production
database, course publication or learner access changes occurred in this repair.

## Integrated release freeze checkpoint

The full Learner, Admin and Coach frontend test run passed **109 files / 2,174
tests**. TypeScript passed for all three applications. These results include
the focused Coach matcher and Admin native-upload transport coverage above;
they do not activate the fail-closed Studio upload runtime or replace exact-SHA
Application and Control-plane CI.

The reviewed release pathspec is
`docs/evidence/20260911_ALPHA_RELEASE_PATHSPEC.txt`. It contains exactly **306
paths**, including itself and the ten previously curated Studio proof images.
It excludes every other screenshot, the unrelated root DOCX, ignored build and
runtime output, local databases, logs, caches and
`docs/evidence/20260910_LOCAL_RESTART_FOLLOWUP.md`. No file was staged or
committed while recording this checkpoint. A read-only Git dry run selected
all 306 entries and no others. Because repository paths include literal square
brackets, the eventual authorized staging command must preserve literal
semantics:

```powershell
git --literal-pathspecs add --pathspec-from-file=docs/evidence/20260911_ALPHA_RELEASE_PATHSPEC.txt
```

A bounded, value-free live read found staging still committed at exact release
`4e8d413b828ab750d7c5e20d1a9320d0f427c823`, migration head
`20260910_0027`; Learner returned 200, Coach redirected to same-host login and
Admin remained behind Cloudflare Access. Production has no current application
release or deployment receipt: Learner and Coach remain on the 503 production
release hold, while Admin remains behind Cloudflare Access. WordPress apex and
`www` both returned 200 and were unchanged. The current foundation is
`foundation-74631e0dd94a1d54a2e2b88bc925e47e0e0c7029`, whose recorded backup
parity is v7.

Infisical staging `/application` supplied all 13 core application names plus
the two staging Resend names. Infisical prod `/application` supplied **0/13**
core names; only names and presence were inspected. Production therefore
remains a separate configuration/bootstrap and action-time approval gate. No
staging value may be copied into production and no manual SQL or live-file
patch is an approved provisioning path.
