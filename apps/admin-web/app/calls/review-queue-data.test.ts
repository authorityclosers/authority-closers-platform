import { expect, it } from "vitest";

import { normalizeReviewQueue, queueHref } from "./review-queue-data";

it("reads the sampled calls with progress and the organisation kind", () => {
  const queue = normalizeReviewQueue({
    pipeline: { key: "analysis-sales", version: 2, title: "Analysis: sales" },
    items: [
      {
        recording_id: "r-1",
        uploaded_at: "2026-10-19T03:00:00Z",
        analysed_at: "2026-10-19T03:05:00Z",
        organisation: { id: "t-1", name: "Fictional Org", kind: "customer" },
        items: 12,
        answered: 3,
        others: 1,
      },
    ],
  });
  expect(queue.pipeline).toEqual({
    key: "analysis-sales",
    version: 2,
    title: "Analysis: sales",
  });
  expect(queue.items[0]).toEqual({
    recordingId: "r-1",
    uploadedAt: "2026-10-19T03:00:00Z",
    analysedAt: "2026-10-19T03:05:00Z",
    organisation: { id: "t-1", name: "Fictional Org", kind: "customer" },
    items: 12,
    answered: 3,
    others: 1,
  });
  expect(normalizeReviewQueue({}).items).toEqual([]);
});

it("flips one option in the queue's address and keeps the other", () => {
  expect(queueHref({ sandbox: false, done: false }, "sandbox")).toBe(
    "/analysis-review?sandbox=1",
  );
  expect(queueHref({ sandbox: true, done: false }, "done")).toBe(
    "/analysis-review?sandbox=1&done=1",
  );
  expect(queueHref({ sandbox: true, done: false }, "sandbox")).toBe(
    "/analysis-review",
  );
});
