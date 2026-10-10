import type { CallRecord } from "./call-record-contract";
import type { SalesReport, Transcript } from "./report-contract";
import { REPORT_PILLARS } from "./report-pillars";

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
export const DOCUMENT_CHAPTERS = REPORT_PILLARS;
