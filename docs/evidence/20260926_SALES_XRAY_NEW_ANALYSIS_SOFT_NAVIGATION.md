# New analysis after opening a saved report

## Reproduction and repair

Observed in the authenticated staging browser on web `13ac5242bd4e8b191d65178fda013ba55dad9f16`: open a saved report from Calls, then click the sidebar **New analysis** link. The URL becomes `/?new=1`, but the previous report and audio dock remain mounted. The report resets to Overview instead of displaying upload.

Next reuses `AcquisitionStudio` during this route transition. Its existing-call effect cleared report state for a new call ID, but only updated its selector reference when the prop became `null`. A new-call route intentionally suppresses remembered-call restoration, leaving the old report state without a replacement.

The effect now clears the previous call's presentation, plan/status state and playback when leaving that selector for a fresh entry. It retains the stored recording, remembered selector, local file selection and authentication continuation. It does not mutate a call, start an upload, accept consent or request inference. Existing cleanup prevents an old in-flight fetch from repopulating the report.

## Validation

- A mounted-tree regression loads a saved report, navigates to New analysis, verifies an enabled upload input and no report/audio dock, then reopens the saved report. No non-GET request is made and the remembered call remains.
- A delayed fetch for another call resolves after navigation to New analysis; it cannot restore the old report or fetch that call's report.
- Node 24.19.0: acquisition-studio and report-modes suites passed, **116 tests**.
- TypeScript, focused ESLint and `git diff --check` passed.

Implementation was delegated to Opus under the included subscription allowance, with no provider APIs, browser or shell tools available to that task. Root reviewed the patch and ran the checks. Deployment and a browser replay on the resulting source remain separate acceptance steps; this document is not evidence of production activation.
