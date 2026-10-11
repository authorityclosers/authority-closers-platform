// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { InitialSessionProvider } from "../initial-session";
import { WorkspaceAccessContext } from "../workspace-access";
import { OrganisationView } from "./organisation-view";
import { ORGANISATION_PATHS, seededOrganisation } from "./organisation-seed";

vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ownerId = "00000000-0000-4000-8000-000000000001";
const tenantId = "00000000-0000-4000-8000-000000000004";
const context = { personId: ownerId, sessionId: "s-1", tenantId };
const organisation = {
  tenant_id: tenantId,
  name: "Fictional Studio",
  role: "owner",
  verified_domains: [],
  auto_join: false,
  member_count: 2,
};
const members = {
  members: [
    {
      person_id: ownerId,
      invite_id: null,
      name: "Asha",
      email: "asha@example.com",
      role: "owner",
      status: "active",
      joined_at: "2026-09-01T12:00:00Z",
      last_active_at: "2026-10-01T12:00:00Z",
      minutes_used_30d: 12,
      calls_30d: 3,
    },
  ],
};
const activity = { members: [], calls: [], per_day: [], per_rep: [] };
const initial = {
  organisation: { status: 200, body: organisation },
  members: { status: 200, body: members },
  activity: { status: 200, body: activity },
};

let fetchMock: ReturnType<typeof vi.fn>;
let root: Root | undefined;
beforeEach(() => {
  window.history.replaceState(null, "", "/organisation");
  fetchMock = vi.fn(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  vi.unstubAllGlobals();
});

const page = (sessionId = "s-1") => (
  <InitialSessionProvider
    value={{
      identity: { person_id: ownerId, session_id: sessionId },
      directory: { selected_tenant_id: tenantId },
    }}
  >
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context,
        workspaces: [
          {
            tenant_id: tenantId,
            kind: "organisation",
            name: "Fictional Studio",
            role: "owner",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <OrganisationView initial={initial} />
    </WorkspaceAccessContext.Provider>
  </InitialSessionProvider>
);

const pageReads = () =>
  fetchMock.mock.calls.filter(([url]) =>
    Object.values(ORGANISATION_PATHS).includes(String(url) as never),
  ).length;

it("takes only successful, well-formed server reads", () => {
  expect(seededOrganisation(initial).organisation?.name).toBe(
    "Fictional Studio",
  );
  expect(
    seededOrganisation({
      organisation: {
        status: 404,
        body: { detail: "No organisation selected." },
      },
      members: { status: 200, body: { nope: [] } },
    }),
  ).toEqual({
    organisation: undefined,
    members: undefined,
    activity: undefined,
  });
  expect(seededOrganisation(null)).toEqual({
    organisation: undefined,
    members: undefined,
    activity: undefined,
  });
});

it("arrives whole from the server's reads and starts without reading them again", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  host.innerHTML = renderToString(page());
  expect(host.querySelector("h1")?.textContent).toBe("Fictional Studio");
  expect(host.textContent).toContain("2 people");
  expect(host.textContent).toContain("Your role:");
  const recoverable = vi.fn();
  await act(async () => {
    root = hydrateRoot(host, page(), { onRecoverableError: recoverable });
  });
  expect(recoverable).not.toHaveBeenCalled();
  expect(host.textContent).toContain("2 people");
  expect(pageReads()).toBe(0);
  host.remove();
});

it("reads in the browser for another session (signed in again in place)", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const { createRoot } = await import("react-dom/client");
  root = createRoot(host);
  await act(async () => root?.render(page("s-0")));
  expect(pageReads()).toBe(3);
  host.remove();
});
