/** Sensitive-segment marks (ADR 0051): ids only, never passage text. */
import { read } from "../lib/read";

export const CATEGORIES = [
  { value: "SENSITIVE_FINANCIAL", label: "Financial" },
  { value: "SENSITIVE_LEGAL", label: "Legal" },
] as const;
export const REASON_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 ._:#/-]{2,79}$/;

export type Mark = {
  id: string;
  revision: string;
  segmentId: string;
  category: string;
  action: "mark" | "release";
  supersedes: string | null;
  source: string;
  reason: string;
  createdAt: string | null;
};
export type RecordingMarks = {
  recordingId: string;
  revisions: { revision: string; segments: number }[];
  marks: Mark[];
};

export function normalizeMarks(raw: unknown): RecordingMarks {
  const body = read.object(raw);
  return {
    recordingId: read.string(body.recording_id),
    revisions: read.array(body.transcript_revisions).map((item) => {
      const row = read.object(item);
      return {
        revision: read.string(row.revision),
        segments: read.number(row.segment_count),
      };
    }),
    marks: read.array(body.marks).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.mark_id),
        revision: read.string(row.transcript_revision),
        segmentId: read.string(row.segment_id),
        category: read.string(row.category),
        action: row.action === "release" ? "release" : "mark",
        supersedes: read.optionalString(row.supersedes_mark_id),
        source: read.string(row.source, "operator"),
        reason: read.string(row.reason_ref),
        createdAt: read.optionalString(row.created_at),
      };
    }),
  };
}

/** Marks still in force: a mark nobody has released. */
export function activeMarks(marks: Mark[]): Mark[] {
  const released = new Set(
    marks
      .filter((mark) => mark.action === "release")
      .map((mark) => mark.supersedes),
  );
  return marks.filter(
    (mark) => mark.action === "mark" && !released.has(mark.id),
  );
}

export const categoryLabel = (value: string) =>
  CATEGORIES.find((category) => category.value === value)?.label ?? value;
