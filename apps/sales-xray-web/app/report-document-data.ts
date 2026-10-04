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
};

export const DOCUMENT_CHAPTERS = [
  { id: "overview", label: "Overview" },
  { id: "moments", label: "Moments" },
  { id: "analysis", label: "Analysis" },
  { id: "coaching", label: "Coaching" },
  { id: "transcript", label: "Transcript appendix" },
];
