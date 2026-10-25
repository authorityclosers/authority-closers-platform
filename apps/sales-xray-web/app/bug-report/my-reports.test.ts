import { beforeEach, expect, it, vi } from "vitest";

import type { MyReport } from "./bug-report-client";

const myReports = vi.fn<() => Promise<MyReport[]>>();
vi.mock("./bug-report-client", () => ({ myReports: () => myReports() }));

import { lookForFixes, newlyFixed, rememberSent } from "./my-reports";

const HOUR = 3600 * 1000;

function report(bugId: string, status: string): MyReport {
  return {
    bugId,
    createdAt: "2026-10-23T08:00:00Z",
    words: `Report ${bugId}`,
    status,
    statusAt: "2026-10-23T09:00:00Z",
  };
}

beforeEach(() => {
  window.localStorage.clear();
  myReports.mockReset();
  myReports.mockResolvedValue([]);
});

it("never asks when nothing was sent from this device", async () => {
  expect(await lookForFixes(10 * HOUR)).toEqual([]);
  expect(myReports).not.toHaveBeenCalled();
});

it("after a send, says once when that report is fixed, then stops asking", async () => {
  rememberSent("b-1");
  myReports.mockResolvedValue([report("b-1", "in_progress")]);
  expect(await lookForFixes(10 * HOUR)).toEqual([]);
  expect(myReports).toHaveBeenCalledTimes(1);

  // At most every six hours.
  expect(await lookForFixes(12 * HOUR)).toEqual([]);
  expect(myReports).toHaveBeenCalledTimes(1);

  myReports.mockResolvedValue([report("b-1", "fixed")]);
  const fixed = await lookForFixes(17 * HOUR);
  expect(fixed.map((item) => item.bugId)).toEqual(["b-1"]);

  // Everything sent is settled now: no more requests.
  expect(await lookForFixes(30 * HOUR)).toEqual([]);
  expect(myReports).toHaveBeenCalledTimes(2);
});

it("counts only reports that were open when last seen", () => {
  const reports = [
    report("a", "fixed"),
    report("b", "verified"),
    report("c", "fixed"),
  ];
  expect(newlyFixed(reports, null)).toEqual([]);
  expect(
    newlyFixed(reports, { a: "new", b: "fixed" }).map((item) => item.bugId),
  ).toEqual(["a"]);
});

it("says Received, Fixing and Solved back in the app", async () => {
  const { STATUS_WORDS } = await import("./my-reports");
  expect(
    ["new", "triaged", "in_progress", "fixed", "verified"].map(
      (status) => STATUS_WORDS[status],
    ),
  ).toEqual(["Received", "Received", "Fixing", "Solved", "Solved"]);
});
