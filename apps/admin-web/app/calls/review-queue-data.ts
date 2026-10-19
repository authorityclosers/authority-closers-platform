/**
 * Review 2.0's queue (GET /v1/admin/conversation/review/queue): the calls a
 * pipeline samples for review, newest first, with this reviewer's progress.
 * Pure.
 */
import { read } from "../lib/read";
import { asKind, type WorkspaceKind } from "../lib/workspaces";

export type QueueCall = {
  recordingId: string;
  uploadedAt: string | null;
  analysedAt: string | null;
  organisation: { id: string; name: string; kind: WorkspaceKind };
  items: number;
  answered: number;
  others: number;
};

export type ReviewQueue = {
  pipeline: { key: string; version: number; title: string };
  items: QueueCall[];
};

export function normalizeReviewQueue(raw: unknown): ReviewQueue {
  const body = read.object(raw);
  const pipeline = read.object(body.pipeline);
  return {
    pipeline: {
      key: read.string(pipeline.key, "analysis-sales"),
      version: read.number(pipeline.version, 1),
      title: read.string(pipeline.title, "Analysis review"),
    },
    items: read.array(body.items).map((item) => {
      const row = read.object(item);
      const organisation = read.object(row.organisation);
      return {
        recordingId: read.string(row.recording_id),
        uploadedAt: read.optionalString(row.uploaded_at),
        analysedAt: read.optionalString(row.analysed_at),
        organisation: {
          id: read.string(organisation.id),
          name: read.string(organisation.name, "Unknown organisation"),
          kind: asKind(organisation.kind),
        },
        items: read.number(row.items),
        answered: read.number(row.answered),
        others: read.number(row.others),
      };
    }),
  };
}

/** The queue's own address with one option flipped (?sandbox=1, ?done=1). */
export function queueHref(
  current: { sandbox: boolean; done: boolean },
  flip: "sandbox" | "done",
): string {
  const next = { ...current, [flip]: !current[flip] };
  const query = new URLSearchParams();
  if (next.sandbox) query.set("sandbox", "1");
  if (next.done) query.set("done", "1");
  const text = query.toString();
  return `/analysis-review${text ? `?${text}` : ""}`;
}
