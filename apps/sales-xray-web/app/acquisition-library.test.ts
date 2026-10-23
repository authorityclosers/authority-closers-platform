import { expect, it } from "vitest";

import { parseSubmissionLibraryPage } from "./acquisition-client";

const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const cursor = "33333333-3333-4333-8333-333333333333";

function row(id = firstId) {
  return {
    submission_id: id,
    created_at: "2026-09-14T06:30:00Z",
    duration_seconds: 61,
    state: "processing",
    has_report: false,
  };
}

it("strictly parses the bounded account library contract", () => {
  expect(
    parseSubmissionLibraryPage({
      submissions: [row(), row(secondId)],
      next_cursor: cursor,
    }),
  ).toEqual({
    submissions: [
      {
        id: firstId,
        createdAt: "2026-09-14T06:30:00Z",
        durationSeconds: 61,
        state: "processing",
        hasReport: false,
        label: null,
      },
      {
        id: secondId,
        createdAt: "2026-09-14T06:30:00Z",
        durationSeconds: 61,
        state: "processing",
        hasReport: false,
        label: null,
      },
    ],
    nextCursor: cursor,
  });
});

it("accepts the C1 call-label fields and still rejects invalid labels", () => {
  expect(
    parseSubmissionLibraryPage({
      submissions: [
        { ...row(), display_name: "Renewal review", display_name_revision: 2 },
        { ...row(secondId), display_name: null, display_name_revision: 0 },
      ],
      next_cursor: null,
    }).submissions.map((submission) => submission.label),
  ).toEqual([
    { displayName: "Renewal review", revision: 2 },
    { displayName: null, revision: 0 },
  ]);
  expect(() =>
    parseSubmissionLibraryPage({
      submissions: [{ ...row(), display_name: "Half present" }],
      next_cursor: null,
    }),
  ).toThrow();
});

it.each([
  ["missing list", { next_cursor: null }],
  [
    "extra top-level field",
    { submissions: [], next_cursor: null, person_id: "leak" },
  ],
  ["non UUID id", { submissions: [row("not-a-uuid")], next_cursor: null }],
  [
    "invalid datetime",
    {
      submissions: [{ ...row(), created_at: "14 Sep 2026" }],
      next_cursor: null,
    },
  ],
  [
    "zero duration",
    { submissions: [{ ...row(), duration_seconds: 0 }], next_cursor: null },
  ],
  [
    "milliseconds field",
    { submissions: [{ ...row(), duration_ms: 61_000 }], next_cursor: null },
  ],
  ["duplicate row", { submissions: [row(), row()], next_cursor: null }],
])("fails closed for %s", (_label, value) => {
  expect(() => parseSubmissionLibraryPage(value)).toThrow();
});

// Approved map, slice 7 (22 Oct 2026): include_leads=true names a call's lead.
it("reads a call's lead exactly, and refuses a malformed one", () => {
  const lead = {
    lead_id: "66666666-6666-4666-8666-666666666666",
    name: "meera fictional",
    stage: "interested",
    step: "site_visit",
    pipeline: "main",
  };
  expect(
    parseSubmissionLibraryPage({
      submissions: [{ ...row(), lead }, row(secondId)],
      next_cursor: null,
    }).submissions.map((submission) => submission.lead),
  ).toEqual([
    {
      leadId: lead.lead_id,
      name: "meera fictional",
      stage: "interested",
      step: "site_visit",
      pipeline: "main",
    },
    undefined,
  ]);
  for (const bad of [
    { ...lead, stage: "maybe" },
    { ...lead, lead_id: "not-a-uuid" },
    { ...lead, name: " " },
    { ...lead, phone: "+91 98765 43210" },
    null,
  ])
    expect(() =>
      parseSubmissionLibraryPage({
        submissions: [{ ...row(), lead: bad }],
        next_cursor: null,
      }),
    ).toThrow();
});
