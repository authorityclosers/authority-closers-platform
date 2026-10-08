import { expect, it } from "vitest";
import { parseSubmissionLibraryPage } from "./acquisition-client";

const submissionId = "11111111-1111-4111-8111-111111111111";
const personId = "22222222-2222-4222-8222-222222222222";
const row = {
  submission_id: submissionId,
  created_at: "2026-10-04T09:00:00+00:00",
  duration_seconds: 90,
  display_name: "Fictional discovery call",
  display_name_revision: 1,
  state: "report_ready",
  has_report: true,
};
const parse = (fields: Record<string, unknown> = {}) =>
  parseSubmissionLibraryPage({
    submissions: [{ ...row, ...fields }],
    next_cursor: submissionId,
  });

it.each(["Fictional Rep", "f***@example.test"])(
  "accepts the complete owner pair and preserves server name %s",
  (name) => {
    const page = parse({ owner_person_id: personId, owner_name: name });
    expect(page.submissions[0]).toEqual({
      id: submissionId,
      createdAt: row.created_at,
      durationSeconds: 90,
      label: { displayName: row.display_name, revision: 1 },
      state: "report_ready",
      hasReport: true,
      owner: { personId, name },
    });
    expect(page.nextCursor).toBe(submissionId);
  },
);

it("omits owner entirely from Personal, member and old-server rows", () => {
  expect(parse().submissions[0]).not.toHaveProperty("owner");
});

it.each([
  { owner_person_id: personId },
  { owner_name: "Fictional Rep" },
  { owner_person_id: undefined, owner_name: "Fictional Rep" },
  { owner_person_id: "not-a-uuid", owner_name: "Fictional Rep" },
  { owner_person_id: null, owner_name: "Fictional Rep" },
  { owner_person_id: 42, owner_name: "Fictional Rep" },
  { owner_person_id: personId, owner_name: null },
  { owner_person_id: personId, owner_name: undefined },
  { owner_person_id: personId, owner_name: 42 },
  { owner_person_id: personId, owner_name: "" },
  { owner_person_id: personId, owner_name: " \t " },
  { owner_person_id: personId, owner_name: "Fictional Rep", role: "owner" },
  { owner_person_id: personId, owner_name: "Fictional Rep", email: "private" },
  {
    owner_person_id: personId,
    owner_name: "Fictional Rep",
    duration_ms: 90000,
  },
  {
    owner_person_id: personId,
    owner_name: "Fictional Rep",
    display_name_revision: -1,
  },
  {
    owner_person_id: personId,
    owner_name: "Fictional Rep",
    created_at: "yesterday",
  },
])("rejects malformed pairs and unrelated fields: %j", (fields) => {
  expect(() => parse(fields)).toThrow("acquisition_library_submission");
});
