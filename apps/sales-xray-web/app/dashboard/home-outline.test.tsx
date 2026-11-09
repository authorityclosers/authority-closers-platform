import { act, type AnchorHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";
import { DashboardSkeleton } from "./dashboard-skeleton";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => new Response("{}", { status: 404 })),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

// The workspace list is still on its way: who is looking is not known yet.
const listing: WorkspaceAccessValue = {
  status: "loading",
  authenticated: null,
  context: null,
  retry: () => {},
};

async function draw(access: WorkspaceAccessValue) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <DashboardSkeleton />
      </WorkspaceAccessContext.Provider>,
    ),
  );
}

// Orchestrator, 9 Nov 2026: on 3G the route's loading screen drew the old
// dashboard's outline ("Last 30 days", "All reports", a chart) for 1 to 7 s
// before Home. It draws Home's own outline, for the role this device saw last.
it("outlines a seller's Home before this device has seen a role", async () => {
  await draw(listing);
  expect(host.querySelector('[data-mode="mine"]')).not.toBeNull();
  expect(host.querySelector('[data-area="cards"]')).not.toBeNull();
  expect(host.querySelector('[data-area="side"] [inert]')).not.toBeNull();
  expect(host.textContent).toContain("Today's overview");
  expect(host.textContent).not.toContain("Last 30 days");
});

it("outlines the team's floor where this device last saw an owner", async () => {
  window.localStorage.setItem("sx:home-role", "manager");
  await draw(listing);
  expect(host.querySelector('[data-mode="team"]')).not.toBeNull();
  expect(host.textContent).toContain("tried today");
  expect(host.textContent).toContain("Needs you now");
  expect(host.textContent).not.toContain("Last 30 days");
});

it("keeps the dashboard's outline where this device last saw no organisation", async () => {
  window.localStorage.setItem("sx:home-role", "none");
  await draw(listing);
  expect(host.querySelector("[data-mode]")).toBeNull();
  expect(host.textContent).toContain("Last 30 days");
});

it("keeps the role the workspace list gives, for the next visit", async () => {
  await draw({
    status: "ready",
    authenticated: true,
    context: {
      personId: "person-1",
      sessionId: "session-1",
      tenantId: "org-1",
    },
    workspaces: [
      {
        tenant_id: "org-1",
        kind: "organisation",
        name: "Fictional Org",
        role: "owner",
        sales_xray_enabled: true,
      },
    ],
    retry: () => {},
  });
  expect(window.localStorage.getItem("sx:home-role")).toBe("manager");
  expect(host.querySelector('[data-mode="team"]')).not.toBeNull();
});
