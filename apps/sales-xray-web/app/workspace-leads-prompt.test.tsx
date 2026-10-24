// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("./notice-center", () => notices);
vi.mock("./early-reads", () => ({ dropEarlyReads: vi.fn() }));

import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";
import {
  WorkspaceLeadsPrompt,
  leadsOffer,
  offerWords,
  parseWorkspaceLeads,
} from "./workspace-leads-prompt";

const PERSONAL = "00000000-0000-4000-8000-000000000001";
const ORG = "00000000-0000-4000-8000-000000000002";
const OTHER = "00000000-0000-4000-8000-000000000003";

const WORKSPACES = [
  {
    tenant_id: PERSONAL,
    kind: "personal" as const,
    name: "Personal",
    role: null,
    sales_xray_enabled: true,
  },
  {
    tenant_id: ORG,
    kind: "organisation" as const,
    name: "Fictional Homes",
    role: "member" as const,
    sales_xray_enabled: true,
  },
  {
    tenant_id: OTHER,
    kind: "organisation" as const,
    name: "Fictional Labs",
    role: "admin" as const,
    sales_xray_enabled: true,
  },
];

const signedIn = (
  tenantId: string,
  workspaces = WORKSPACES,
): WorkspaceAccessValue => ({
  status: "ready",
  authenticated: true,
  workspaces,
  context: { personId: "p", sessionId: "s", tenantId },
  retry: () => {},
});

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  notices.notify.mockReset();
  window.sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function show(access: WorkspaceAccessValue | null) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <WorkspaceLeadsPrompt />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await act(async () => new Promise((done) => setTimeout(done, 0)));
}

it("offers the workspace with the most of her leads when the open one has none", () => {
  const counts = new Map([
    [PERSONAL, 0],
    [ORG, 383],
    [OTHER, 12],
  ]);
  const offer = leadsOffer(PERSONAL, WORKSPACES, counts);
  expect(offer).toEqual({ tenantId: ORG, name: "Fictional Homes", leads: 383 });
  expect(offerWords(offer!)).toBe("You have 383 leads in Fictional Homes");
  expect(offerWords({ ...offer!, leads: 1 })).toBe(
    "You have 1 lead in Fictional Homes",
  );
  // Nothing to say when the open workspace has leads, or no other one does.
  expect(leadsOffer(ORG, WORKSPACES, counts)).toBeNull();
  expect(leadsOffer(PERSONAL, WORKSPACES, new Map([[PERSONAL, 0]]))).toBeNull();
  expect(leadsOffer(null, WORKSPACES, counts)).toBeNull();
});

it("reads the counts strictly", () => {
  expect(
    parseWorkspaceLeads({ workspaces: [{ tenant_id: ORG, leads: 4 }] }),
  ).toEqual(new Map([[ORG, 4]]));
  expect(
    parseWorkspaceLeads({ workspaces: [{ tenant_id: ORG, leads: -1 }] }),
  ).toBeNull();
  expect(parseWorkspaceLeads({ nope: [] })).toBeNull();
});

it("shows one corner card with Switch, which selects the workspace and reloads", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url === "/v1/me/sales-xray-workspaces/leads")
        return Response.json({
          workspaces: [
            { tenant_id: PERSONAL, leads: 0 },
            { tenant_id: ORG, leads: 383 },
          ],
        });
      return Response.json({ tenant_id: ORG });
    }),
  );
  const reload = vi
    .spyOn(window.location, "reload")
    .mockImplementation(() => {});

  await show(signedIn(PERSONAL));

  expect(notices.notify).toHaveBeenCalledTimes(1);
  const notice = notices.notify.mock.calls[0][0];
  expect(notice).toMatchObject({
    tone: "info",
    title: "You have 383 leads in Fictional Homes",
    dismissLabel: "Not now",
  });
  await act(async () => notice.action.run());
  await act(async () => new Promise((done) => setTimeout(done, 0)));
  const select = calls.find((call) => call.url === "/v1/context");
  expect(select?.init?.method).toBe("POST");
  expect(JSON.parse(String(select?.init?.body))).toEqual({ tenant_id: ORG });
  expect(reload).toHaveBeenCalled();

  // Once per workspace per tab.
  notices.notify.mockReset();
  await act(async () => root.unmount());
  root = createRoot(host);
  await show(signedIn(PERSONAL));
  expect(notices.notify).not.toHaveBeenCalled();
});

it("reads nothing until signed in with a workspace open, or with a single workspace", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await show(null);
  await show({
    status: "unauthenticated",
    authenticated: false,
    context: null,
    retry: () => {},
  });
  await show({ ...signedIn(PERSONAL), status: "chooser", context: null });
  await show(signedIn(PERSONAL, WORKSPACES.slice(0, 1)));
  expect(fetcher).not.toHaveBeenCalled();
  expect(notices.notify).not.toHaveBeenCalled();
});
