import {
  parseAcquisitionReport,
  parseTranscript,
  type SalesReport,
  type Transcript,
} from "../../../report-contract";
import fixture from "./v8-fictional.json";

const SUBMISSION = "22222222-2222-4222-8222-222222222222";
const RECORDING = "11111111-1111-4111-8111-111111111111";

/**
 * H's fictional v8 projection (account access, with `pillars`) read through
 * the same codec a real call uses, so this page shows exactly what a report
 * looks like once the analysis supplies Dipak's six pillars itself.
 */
export function v8Report(): { report: SalesReport; transcript: Transcript } {
  const transcript = parseTranscript(
    fixture.transcript,
    fixture.transcript.source_sha256,
  );
  const { report } = parseAcquisitionReport(
    {
      schema: "ac.sales-xray.report-envelope/2",
      submission_id: SUBMISSION,
      recording_id: RECORDING,
      run_id: "fixture-v8-run",
      source_sha256: transcript.source_sha256,
      transcript_revision: transcript.revision,
      source_label: "Fictional v8 contract",
      report: fixture.account,
    },
    { submissionId: SUBMISSION, recordingId: RECORDING },
    transcript,
  );
  return { report, transcript };
}
