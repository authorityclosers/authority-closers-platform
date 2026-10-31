import { beforeEach, expect, it, vi } from "vitest";

import { serverReads, serverApiOrigin } from "../server-reads";
import { serverLeads } from "./leads-server";
import { firstPageFor, type ServerLeads } from "./leads-seed";

vi.mock("../server-reads", () => ({
  SERVER_READ_BUDGET_MS: 800,
  serverApiOrigin: vi.fn(() => "http://api.example.test"),
  serverReads: vi.fn(),
  SESSION_PATHS: ["/v1/me/workspaces", "/v1/me/sales-xray-workspaces"],
}));
const identity = JSON.stringify([
  "fictional-person",
  "fictional-session",
  "fictional-workspace",
]);
const desk = {
  me: { person_id: "fictional-person", can_manage: true },
  queue: [],
  counts: { open: 2000 },
  numbers: { calls: 0 },
};
const page = { leads: [], total: 2000, next_offset: 50 };
const reads = () => ({
  "/v1/me/workspaces": {
    status: 200,
    body: {
      person_id: "fictional-person",
      session_id: "fictional-session",
      selected_tenant_id: "fictional-workspace",
    },
  },
  "/v1/me/sales-xray-workspaces": {
    status: 200,
    body: { selected_tenant_id: "fictional-workspace" },
  },
  "/v1/lead-desk": { status: 200, body: desk },
});
const load = (query: Record<string, string> = {}) =>
  serverLeads(Promise.resolve(query));
beforeEach(() => {
  vi.mocked(serverApiOrigin).mockReturnValue("http://api.example.test");
  vi.mocked(serverReads)
    .mockReset()
    .mockResolvedValueOnce(reads())
    .mockResolvedValueOnce({
      "/v1/lead-desk/leads?scope=team&side=inbound&view=to_call": {
        status: 200,
        body: page,
      },
    });
});
it("reads only the first page through the existing bounded private server reader", async () => {
  expect(await load()).toMatchObject({
    identity,
    firstPage: { scope: "team", page },
  });
  expect(serverReads).toHaveBeenNthCalledWith(
    1,
    ["/v1/me/workspaces", "/v1/me/sales-xray-workspaces", "/v1/lead-desk"],
    800,
  );
  // The list gets what is left of the same 800 ms.
  const left = vi.mocked(serverReads).mock.calls[1][1] as number;
  expect(left).toBeGreaterThan(0);
  expect(left).toBeLessThanOrEqual(800);
});
it("leaves the list to the browser once the budget is spent", async () => {
  const now = vi.spyOn(Date, "now").mockReturnValue(1000);
  vi.mocked(serverReads)
    .mockReset()
    .mockImplementationOnce(async () => {
      now.mockReturnValue(1800);
      return reads();
    });
  expect(await load()).toMatchObject({ identity, firstPage: null });
  expect(serverReads).toHaveBeenCalledOnce();
  now.mockRestore();
});
it("falls back before reading query parameters in a static build", async () => {
  vi.mocked(serverApiOrigin).mockReturnValue(null);
  expect(await serverLeads(new Promise(() => {}))).toBeNull();
  expect(serverReads).not.toHaveBeenCalled();
});
it.each<Record<string, string>>([
  { tab: "desk" },
  { tab: "all", who: "mine" },
  { tab: "all", q: "fictional" },
  { tab: "all", stage: "won" },
  { side: "cold" },
  { view: "all" },
  { view: "follow_ups", when: "today" },
])(
  "leaves other views, saved filters and their scope to the normal reader (%j)",
  async (query) => {
    expect(await load(query)).toBeNull();
    expect(serverReads).not.toHaveBeenCalled();
  },
);
it("does not accept data when the selected workspace or desk person differs", async () => {
  const wrongWorkspace = reads();
  wrongWorkspace["/v1/me/workspaces"].body.selected_tenant_id =
    "other-workspace";
  vi.mocked(serverReads).mockReset().mockResolvedValueOnce(wrongWorkspace);
  expect(await load()).toBeNull();
  vi.mocked(serverReads)
    .mockReset()
    .mockResolvedValueOnce({
      ...reads(),
      "/v1/lead-desk": {
        status: 200,
        body: { ...desk, me: { ...desk.me, person_id: "other-person" } },
      },
    });
  expect(await load()).toBeNull();
});
it("keeps the desk when the list times out and rejects a malformed desk", async () => {
  vi.mocked(serverReads)
    .mockReset()
    .mockResolvedValueOnce(reads())
    .mockResolvedValueOnce(null);
  expect(await load()).toMatchObject({ identity, firstPage: null });
  vi.mocked(serverReads)
    .mockReset()
    .mockResolvedValueOnce({
      ...reads(),
      "/v1/lead-desk": { status: 200, body: null },
    });
  expect(await load()).toBeNull();
});
it("uses mine for a seller, leaving team permission to the ordinary API", async () => {
  vi.mocked(serverReads)
    .mockReset()
    .mockResolvedValueOnce({
      ...reads(),
      "/v1/lead-desk": {
        status: 200,
        body: { ...desk, me: { ...desk.me, can_manage: false } },
      },
    })
    .mockResolvedValueOnce({
      "/v1/lead-desk/leads?scope=mine&side=inbound&view=to_call": {
        status: 200,
        body: page,
      },
    });
  expect(await load()).toMatchObject({ firstPage: { scope: "mine", page } });
});
it("a server page never answers another identity, scope, pipeline or filter", () => {
  const seed = {
    identity,
    desk,
    firstPage: { scope: "team", page },
  } as unknown as ServerLeads;
  const opening = { side: "inbound", view: "to_call" };
  const ask = { scope: "team", stage: "all", query: "", more: opening };
  expect(firstPageFor(seed, identity, ask)).toBe(page);
  expect(firstPageFor(null, undefined, ask)).toBeNull();
  expect(firstPageFor(seed, "other-identity", ask)).toBeNull();
  for (const change of [
    { scope: "mine" },
    { stage: "won" },
    { stage: "new" },
    // Leads opens on Inbound, To Call (Dipak's handoff, 31 Oct 2026).
    { more: { ...opening, side: "cold" } },
    { more: { ...opening, view: "follow_ups" } },
    { more: { ...opening, step: "new" } },
    { more: null },
    { query: "test" },
    { pipeline: "other" },
    { owner: "other" },
    { more: { ...opening, due: "today" } },
  ])
    expect(firstPageFor(seed, identity, { ...ask, ...change })).toBeNull();
});
