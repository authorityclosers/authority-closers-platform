import { expect, it } from "vitest";

import { normalizeAccess, normalizeDetail } from "./bugs-data";

it("reads the advanced reporter's parts and files with a report", () => {
  const bug = normalizeDetail({
    bug_id: "b1",
    context: {
      trail: [{ event: "sx.tap", detail: { target: "row", screen: 3 } }],
      advanced: {
        steps: ["Open Leads", 4],
        comments: [
          {
            n: 1,
            note: "Wrong stage",
            selector: "li.row > button",
            components: ["LeadRow", 7],
            on_picture: true,
          },
        ],
        calls: [
          { path: "/v1/lead-desk/leads/:id/stage", status: 500, failed: true },
        ],
        speed: { first_byte_ms: 300, memory_mb: "lots" },
        marked: true,
      },
    },
    files: [
      {
        position: 1,
        role: "original",
        name: "screen",
        content_type: "image/webp",
        bytes: 2048,
      },
      {
        position: 2,
        role: "element",
        part: 1,
        name: "part 1",
        content_type: "image/webp",
        bytes: 512,
      },
      { position: 3, role: "unknown", name: "x" },
    ],
  });
  expect(bug.trail[0]?.detail).toEqual({ target: "row" });
  expect(bug.advanced?.steps).toEqual(["Open Leads"]);
  expect(bug.advanced?.comments[0]).toMatchObject({
    n: 1,
    note: "Wrong stage",
    components: ["LeadRow"],
    onPicture: true,
  });
  expect(bug.advanced?.calls[0]).toMatchObject({ status: 500, failed: true });
  expect(bug.advanced?.speed).toEqual({ first_byte_ms: 300 });
  expect(
    bug.files.map((file) => [file.position, file.role, file.part]),
  ).toEqual([
    [1, "original", null],
    [2, "element", 1],
  ]);
  // A plain report has none of it.
  expect(normalizeDetail({ bug_id: "b2", context: {} }).advanced).toBeNull();
});

it("lists who asked for the advanced reporter and where each stands", () => {
  expect(
    normalizeAccess({
      people: [
        {
          person_id: "p1",
          name: "Fictional Tester",
          email: "t@example.test",
          state: "requested",
          since: "2026-10-31T04:30:00Z",
        },
        { person_id: "p2", state: "maybe" },
      ],
    }),
  ).toEqual([
    {
      personId: "p1",
      name: "Fictional Tester",
      email: "t@example.test",
      state: "requested",
      since: "2026-10-31T04:30:00Z",
      note: null,
    },
  ]);
});
