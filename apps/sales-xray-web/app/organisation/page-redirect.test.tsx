import { beforeEach, expect, it, vi } from "vitest";

// sx-redesign (21 Nov 2026): /organisation reaches Settings on the server.
const state = vi.hoisted(() => ({
  built: true,
  reads: null as Record<
    string,
    { status: number; body: unknown } | null
  > | null,
  redirect: vi.fn((to: string) => {
    throw new Error(`redirect ${to}`);
  }),
}));
vi.mock("next/navigation", () => ({ redirect: state.redirect }));
vi.mock("../server-reads", () => ({
  serverReadsBuilt: () => state.built,
  serverReads: async () => state.reads,
}));
vi.mock("./organisation-server", () => ({
  serverOrganisation: async () => null,
}));
vi.mock("./org-hub", () => ({ OrganisationHub: () => null }));

import OrganisationPage from "./page";
import { hubQueryTarget } from "../settings/settings-sections";

const open = (query: Record<string, string | string[]>) =>
  OrganisationPage({ searchParams: Promise.resolve(query) });

beforeEach(() => {
  state.built = true;
  state.reads = { "/v1/organisation": { status: 200, body: {} } };
  state.redirect.mockClear();
});

it("sends an organisation's /organisation to its Settings section at once, query kept", async () => {
  await expect(open({})).rejects.toThrow("redirect /settings");
  await expect(
    open({ tab: "connections", part: "developers", connected: "meta" }),
  ).rejects.toThrow("redirect /settings/developers?connected=meta");
  await expect(open({ tab: "leads", part: "stages" })).rejects.toThrow(
    "redirect /settings/stages",
  );
});

it("keeps the page for Analytics, a personal workspace and a server without reads", async () => {
  await expect(open({ tab: "analytics" })).resolves.toBeTruthy();
  state.reads = { "/v1/organisation": { status: 404, body: null } };
  await expect(open({})).resolves.toBeTruthy();
  state.reads = null;
  await expect(open({})).resolves.toBeTruthy();
  state.built = false;
  state.reads = { "/v1/organisation": { status: 200, body: {} } };
  await expect(open({})).resolves.toBeTruthy();
  expect(state.redirect).not.toHaveBeenCalled();
});

it("works out the Settings address from the hub's query", () => {
  expect(hubQueryTarget(new URLSearchParams("tab=team&x=1"))).toBe(
    "/settings/team?x=1",
  );
  expect(hubQueryTarget(new URLSearchParams("tab=analytics"))).toBeNull();
  expect(hubQueryTarget(new URLSearchParams("tab=nonsense"))).toBe("/settings");
});
