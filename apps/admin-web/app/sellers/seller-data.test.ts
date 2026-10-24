import { expect, it } from "vitest";

import { sellerFixture } from "../review-fixture/seller/seller-fixture";
import {
  DAYS,
  daysFrom,
  normalizeFound,
  normalizeTimeline,
  phoneLine,
  sellerPath,
  serverLine,
  totalsLine,
} from "./seller-data";

it("reads a seller's days and words what reached the server beside the phone", () => {
  const timeline = normalizeTimeline(sellerFixture("gap"));
  expect(timeline.summary).toEqual({
    tone: "bad",
    words:
      "23 Oct: 14 calls, 0 results saved — the phone saved 9 results that never reached the server",
  });
  const [day23, day22] = timeline.timeline;
  expect(day23.label).toBe("23 Oct");
  expect(serverLine(day23.server)).toBe(
    "4 calls placed in the app · 10 calls logged by the phone (7 connected) · 0 results · 0 notes · 0 stage moves",
  );
  expect(phoneLine(day23.phone)).toBe(
    "4 calls started · 9 results saved · 2 stage moves saved · 11 waiting to send · 2 errors shown · 3 slow taps · 5 slow or failed requests · slow to load: lead",
  );
  expect(day23.flags[0]).toEqual({
    tone: "bad",
    words: "9 results saved on the phone, 0 reached the server",
  });
  expect(day23.moments.map((moment) => moment.time)).toEqual([
    "09:00",
    "09:11",
    "10:32",
    "12:45",
    "18:10",
  ]);
  expect(day22.flags).toEqual([]);
  expect(timeline.devices[0]).toMatchObject({
    app: "android",
    store: "Play",
    version: "1.0.26",
    versions: ["1.0.26", "1.0.25"],
  });
  expect(timeline.workspaces.map((item) => item.analytics)).toEqual([
    "on",
    "on",
  ]);
  expect(totalsLine(timeline)).toBe(
    "In 14 days: 7 calls placed in the app · 19 calls logged by the phone · 7 results · 2 notes · 3 stage moves · 1 day with gaps",
  );
});

it("keeps a page standing when the answer is missing or malformed", () => {
  const timeline = normalizeTimeline({
    summary: { tone: "loud", words: 4 },
    days: [{ server: null, phone: null, flags: [{ tone: "odd" }] }],
    workspaces: [{ analytics: "maybe" }],
  });
  expect(timeline.summary).toEqual({ tone: "neutral", words: "" });
  expect(timeline.days).toBe("14");
  expect(timeline.timeline[0].phone).toBeNull();
  expect(phoneLine(timeline.timeline[0].phone)).toBe(
    "No usage data from the phone",
  );
  expect(timeline.timeline[0].flags[0].tone).toBe("warn");
  expect(timeline.workspaces[0].analytics).toBe("on");
  expect(normalizeTimeline(null).timeline).toEqual([]);
});

it("finds people by id, keeps the window choices and builds the address", () => {
  expect(
    normalizeFound({
      person: { id: "p1", name: null, email: "a@example.test" },
    }),
  ).toEqual({ id: "p1", name: null, email: "a@example.test" });
  expect(normalizeFound({ person: {} })).toBeNull();
  expect(DAYS[0]).toBe("14");
  expect(daysFrom("30")).toBe("30");
  expect(daysFrom("90")).toBe("14");
  expect(daysFrom(undefined)).toBe("14");
  expect(sellerPath("p1")).toBe("/sellers/p1");
});
