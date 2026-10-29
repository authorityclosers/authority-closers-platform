// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import {
  cachedLeadData,
  rememberLeadData,
  cachedLeadPage,
  readFirstLeads,
  preloadFirstLeads,
} from "./list-cache";
import { readLeads, type LeadPage } from "./leads-client";
import { forgetLeadData } from "./list-cache-slot";
vi.mock("./leads-client", () => ({ readLeads: vi.fn() }));
const identity = JSON.stringify([
  "fictional-person",
  "fictional-session",
  "cedar",
]);
const ask = { scope: "team" as const, stage: "open" };
const page: LeadPage = {
  leads: [],
  total: 2000,
  next_offset: 50,
  stage_counts: { new: 2000 },
};
afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.mocked(readLeads).mockReset();
});
it("keeps the last first page across reloads, but never across a person, session, workspace or filter", async () => {
  vi.mocked(readLeads).mockResolvedValue(page);
  await readFirstLeads(identity, ask);
  expect(cachedLeadPage(identity, ask)).toEqual(page);
  for (const other of [
    ["another-person", "fictional-session", "cedar"],
    ["fictional-person", "another-session", "cedar"],
    ["fictional-person", "fictional-session", "maple"],
  ])
    expect(cachedLeadPage(JSON.stringify(other), ask)).toBeNull();
  expect(cachedLeadPage(identity, { ...ask, stage: "won" })).toBeNull();
  expect(
    cachedLeadPage(identity, { ...ask, owner: "another-seller" }),
  ).toBeNull();
  expect(cachedLeadPage(identity, { ...ask, pipeline: "partner" })).toBeNull();
  expect(cachedLeadPage(null, ask)).toBeNull();
});
it("shares the warm-up with the list even when it finishes before the desk", async () => {
  vi.mocked(readLeads).mockResolvedValue(page);
  preloadFirstLeads(identity, ask);
  await Promise.resolve();
  await Promise.resolve();
  expect(await readFirstLeads(identity, ask)).toEqual(page);
  expect(readLeads).toHaveBeenCalledTimes(1);
  await readFirstLeads(identity, ask);
  expect(readLeads).toHaveBeenCalledTimes(2); // A later refresh revalidates.
});
it("keeps a day on this device and bounds storage to six answers", () => {
  vi.spyOn(Date, "now").mockReturnValue(1000);
  for (let n = 0; n < 8; n++) rememberLeadData(identity, `question-${n}`, n);
  expect(cachedLeadData(identity, "question-0")).toBeNull();
  expect(cachedLeadData(identity, "question-7")).toBe(7);
  // A new tab or the next launch of the phone app (fresh tab storage).
  sessionStorage.clear();
  vi.mocked(Date.now).mockReturnValue(1000 + 23 * 60 * 60_000);
  expect(cachedLeadData(identity, "question-7")).toBe(7);
  vi.mocked(Date.now).mockReturnValue(1001 + 24 * 60 * 60_000);
  expect(cachedLeadData(identity, "question-7")).toBeNull();
});
it("keeps one identity's leads only, and forgets them on sign-out", () => {
  rememberLeadData(identity, "question", "cedar's");
  const other = JSON.stringify(["another-person", "another-session", "maple"]);
  rememberLeadData(other, "question", "maple's");
  expect(cachedLeadData(identity, "question")).toBeNull();
  expect(localStorage.getItem("sx:leads-cache:v1")).not.toContain("cedar's");
  expect(cachedLeadData(other, "question")).toBe("maple's");
  forgetLeadData();
  expect(cachedLeadData(other, "question")).toBeNull();
  expect(localStorage.getItem("sx:leads-cache:v1")).toBeNull();
});
it("ignores malformed or refused storage and still reads the network", async () => {
  localStorage.setItem("sx:leads-cache:v1", "not-json");
  expect(cachedLeadData(identity, "anything")).toBeNull();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.mocked(readLeads).mockResolvedValue(page);
  expect(await readFirstLeads(identity, ask)).toEqual(page);
});

it("revalidates an abandoned warm-up instead of serving it on a later visit", async () => {
  vi.spyOn(Date, "now").mockReturnValue(1000);
  vi.mocked(readLeads).mockResolvedValue(page);
  preloadFirstLeads(identity, ask);
  await Promise.resolve();
  await Promise.resolve();
  vi.mocked(Date.now).mockReturnValue(11001);
  await readFirstLeads(identity, ask);
  expect(readLeads).toHaveBeenCalledTimes(2);
});
