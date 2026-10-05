import type { CallRecord } from "./call-record-contract";
import type { SalesReport, Transcript } from "./report-contract";

export type DocumentReportData = {
  title?: string;
  workspaceName?: string;
  repName?: string;
  prospectName?: string;
  callType?: string;
  callDate?: string;
  callLength?: string;
  analysedDate?: string;
  analysisBasis?: {
    recordingLength?: string;
    transcriptRevision?: string;
    analysisVersion?: string;
  };
  report?: SalesReport;
  transcript?: Transcript;
  /** Measured numbers and facts; older calls have none. */
  callRecord?: CallRecord | null;
  /** Confirmed speaker names by transcript speaker id. */
  speakerNames?: Record<string, string>;
};

/** Document sections in page order; each is a Word bookmark in the DOCX. */
export const DOCUMENT_CHAPTERS = [
  { id: "overview", label: "Overview" },
  { id: "coaching", label: "Coaching" },
  { id: "moments", label: "Moments" },
  { id: "missed", label: "Missed chances" },
  { id: "skills", label: "Skills" },
  { id: "facts", label: "Facts" },
];
