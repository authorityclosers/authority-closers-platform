import { expect, it } from "vitest";

import {
  appLine,
  bugFilters,
  bugQuery,
  bugsApiPath,
  deviceLine,
  eventText,
  normalizeDetail,
  normalizePage,
} from "./bugs-data";

const ORG = "11111111-1111-4111-8111-111111111111";

it("keeps only known filters from the address, open bugs by default", () => {
  expect(bugFilters({})).toEqual({ view: "open" });
  expect(
    bugFilters({
      status: "in_progress",
      severity: "blocker",
      area: "leads",
      organisation: ORG.toUpperCase(),
      offset: "50",
    }),
  ).toEqual({
    view: "in_progress",
    severity: "blocker",
    area: "leads",
    organisation: ORG,
    offset: 50,
  });
  expect(
    bugFilters({
      status: "done",
      severity: "urgent",
      area: "x",
      organisation: "nope",
      offset: "-3",
    }),
  ).toEqual({ view: "open" });
  expect(bugFilters({ status: "all", severity: "none" })).toEqual({
    view: "all",
    severity: "none",
  });
});

it("builds the address and the API query in a stable order", () => {
  const filters = bugFilters({ status: "fixed", area: "calls", offset: "50" });
  expect(bugQuery(filters)).toBe("status=fixed&area=calls&offset=50");
  expect(bugQuery(filters, ["offset", "view"])).toBe("area=calls");
  expect(bugsApiPath(filters)).toBe(
    "/v1/admin/bugs?status=fixed&area=calls&offset=50",
  );
  expect(bugsApiPath({ view: "all" })).toBe("/v1/admin/bugs");
  expect(bugsApiPath({ view: "open" })).toBe("/v1/admin/bugs?status=open");
});

it("reads a page and one report, with defaults for anything odd", () => {
  const page = normalizePage({
    items: [
      {
        bug_id: "b1",
        number: 12,
        words: "Call button does nothing",
        blocks_work: true,
        status: "triaged",
        severity: "weird",
        area: "leads",
        board_card: "AUT-2301",
        organisation: { id: ORG, name: "Fictional Homes" },
        person: { name: "Asha Fictional", email: "asha@example.test" },
        has_screenshot: true,
        error_count: 2,
      },
    ],
    counts: { new: 3, triaged: 1 },
    next_offset: null,
    organisations: [{ id: ORG, name: "Fictional Homes", count: 4 }],
  });
  expect(page.items[0]).toMatchObject({
    id: "b1",
    number: 12,
    status: "triaged",
    severity: null,
    area: "leads",
    boardCard: "AUT-2301",
    organisation: { id: ORG, name: "Fictional Homes" },
  });
  expect(page.counts).toEqual({
    new: 3,
    triaged: 1,
    in_progress: 0,
    fixed: 0,
    verified: 0,
    closed: 0,
  });
  const detail = normalizeDetail({
    bug_id: "b1",
    number: 12,
    status: "new",
    area: "other",
    board_card: "<script>",
    context: {
      app: {
        channel: "android",
        native_version: "0.3.88",
        release: "abcdef1234567890",
      },
      device: {
        os: "Android 14",
        browser: "Android WebView 141",
        viewport: "390x844",
        touch: true,
        nested: { x: 1 },
      },
      server: { environment: "production", release: "0123456789abcdef" },
      workspace: { role: "member" },
    },
    client_errors: [
      { kind: "http", status: 500, method: "POST", path: "/v1/x" },
    ],
    history: [
      { event_id: "e1", kind: "status", status: "new", actor: "reporter" },
      { event_id: "e2", kind: "board", board_card: "AUT-2301", actor: "board" },
      {
        event_id: "e3",
        kind: "note",
        note: "Seen on a test phone",
        actor: "staff",
        actor_email: "team@example.test",
      },
    ],
    screenshot: { content_type: "image/webp", bytes: 1234, source: "auto" },
  });
  expect(detail.boardCard).toBeNull();
  expect(detail.device).toEqual({
    os: "Android 14",
    browser: "Android WebView 141",
    viewport: "390x844",
    touch: true,
  });
  expect(detail.workspaceRole).toBe("member");
  expect(detail.screenshot).toEqual({ source: "auto", bytes: 1234 });
  expect(appLine(detail.app)).toBe("Android app · 0.3.88 · web abcdef123456");
  expect(deviceLine(detail.device)).toBe(
    "Android 14 · Android WebView 141 · 390x844",
  );
  expect(detail.history.map(eventText)).toEqual([
    "Status: New",
    "Work-board card AUT-2301",
    "Seen on a test phone",
  ]);
  expect(detail.history[2].actorName).toBe("team@example.test");
  expect(normalizeDetail(null).history).toEqual([]);
});
