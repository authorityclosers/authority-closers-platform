import { parseAcquisitionReport, parseTranscript } from "../../report-contract";
import frozen from "./sample-call.json";
import type { SampleReportData } from "./sample-report-view";

/** The sample call's recording, served with the app (public/media). */
export const SAMPLE_AUDIO_SRC = "/media/sample-call.mp3";

/** A fixed id for the sample: its local notes (speaker names, ticks) stay in this browser. */
const SAMPLE_CALL_ID = "00000000-0000-4000-8000-000000000027";

/**
 * The sample report (27 Oct 2026): a fictional call written for new users, a
 * buyer asking about a two-bedroom flat in Pune. Every name in it is made up.
 * It was voiced with ElevenLabs and analysed once on dev through the normal
 * pipeline; its report and transcript are frozen in sample-call.json and read
 * here through the same codec a real call uses. No API read, no AI.
 */
export function sampleCall(): SampleReportData {
  const transcript = parseTranscript(
    frozen.transcript,
    frozen.transcript.source_sha256,
  );
  const { report } = parseAcquisitionReport(
    frozen.report,
    {
      submissionId: frozen.report.submission_id,
      recordingId: frozen.report.recording_id,
    },
    transcript,
  );
  return {
    callId: SAMPLE_CALL_ID,
    report,
    transcript,
    durationMs: transcript.duration_ms,
    languageLabel: "English",
    sourceLabel: "Fictional sample call",
    title: "Sample call: a flat in Pune",
    audioSrc: SAMPLE_AUDIO_SRC,
  };
}
