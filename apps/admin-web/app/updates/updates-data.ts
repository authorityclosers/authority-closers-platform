/** Normalizer for GET /v1/admin/conversation/product-updates. */
import { read } from "../lib/read";

export type Note = {
  key: string;
  version: number;
  title: string;
  items: string[];
  date: string;
  audience: string;
  status: string;
  major: boolean;
  releaseId: string;
  sourcePr: number | null;
  publishedAt: string | null;
};

export const AUDIENCE_LABEL: Record<string, string> = {
  everyone: "Everyone",
  org_admins: "Organisation admins",
  testers: "Testers",
};

export function normalizeNotes(raw: unknown): Note[] {
  return read.array(read.object(raw).notes).map((item) => {
    const row = read.object(item);
    return {
      key: read.string(row.key),
      version: read.number(row.version, 1),
      title: read.string(row.title, "Untitled note"),
      items: read.strings(row.items),
      date: read.string(row.date),
      audience: read.string(row.audience, "everyone"),
      status: read.string(row.status, "draft"),
      major: read.boolean(row.major),
      releaseId: read.string(row.release_id),
      sourcePr: read.optionalNumber(row.source_pr),
      publishedAt: read.optionalString(row.published_at),
    };
  });
}
