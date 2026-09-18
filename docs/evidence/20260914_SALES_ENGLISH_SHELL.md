# English app shell and readable report findings

The user's latest correction supersedes the earlier four-language shell design.
The public standalone and embedded LMS CallStudio now keep navigation, controls
and layout in English. There is no global language selector. Saved transcript,
report text, quotations and timestamps remain literal, including mixed
Devanagari, Marathi and English. Reusable internal copy helpers are retained;
they do not mount a public language switch or provider-management control.

The six report sections remain. Long source quotations now sit under native
keyboard-accessible evidence disclosures so the overview leads with the finding.
Expanding reveals the original quotations and replay buttons. Printing expands
every finding's evidence and then restores the previous disclosure state, even
if the browser repeats its beforeprint event. No score or inference is added.

## Tested here

- 71 UI tests in 10 files pass, including mounted mixed-script rendering,
  escaped HTML-like transcript text, English controls, and print-state recovery.
- Standalone and learner production builds and ESLint pass. An initial lint warning for a
  leftover unused language type was corrected before the final build/check.
- Fresh production-build browser proof passes: six sections, source seek,
  blocked/missing playback recovery, keyboard evidence expansion, retained
  search/sound state, Devanagari search, 320/390/1280px layouts and complete PDF.
  This harness uses synthetic API responses and substitutes media.play only for
  its recovery cases. It makes no provider request.
- Actual saved real-call presentation also passes against this built CallStudio:
  matching original recording SHA, 144 literal transcript segments loaded through
  pagination, mixed-script search, unmodified report summary and real source
  playback. Its local read responses are intercepted; this is presentation and
  playback proof, not authenticated backend or hosted acceptance.

Portable raw JUnit, build log, browser receipt, synthetic screenshots/PDF and
hash manifest are in `sales-xray-english-shell-20260914/`. Browser source hashes
identify the exact working bytes tested; the source commit follows these runs.
The prior 39dcb36 packet retains actual HTTP/identity/PostgreSQL/native proofs.
Shared auth, contracts, migrations, quotas and storage are unchanged here.

## Private owner preview

The saved source-reviewed draft is rendered at
`D:/AuthorityClosers-Private/SalesXray-Test/approved-call-20260913/app-report-20260914/Your-Sales-Xray-Report.pdf`.
It is 11 pages, containing all 12 finding titles and 8 factor labels. The full
144-segment transcript remains in the app; it is not appended to this PDF.
The private directory also holds actual browser screenshots, a presentation
receipt and PDF inspection. Real source content and images stay outside Git.
The first preview harness assumption that all transcript rows appear at once
was corrected to exercise the existing bounded pagination. A capture taken
during the entry animation was replaced after waiting for visible final paint.

No new inference was requested. This reuses the previous coordinator-corrected
source-reviewed proposal after earlier model drafts failed semantic checks;
it is still awaiting Dipak and Suyash, not a newly passing model benchmark.

## Release status

SSH ac was rechecked successfully after the user's authentication update.
Read-only VPS checks showed 12,924 MiB available memory and 139 GiB available
root storage. Existing core containers were healthy; these values alone do not
establish processing capacity. The release coordinator remains the sole owner
of combined CI/images/installers. This UI is not claimed staged or production
published by this receipt, and no new hosted real-call processing is claimed.
