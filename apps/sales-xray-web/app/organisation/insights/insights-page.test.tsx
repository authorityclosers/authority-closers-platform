// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/organisation/insights",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: React.ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("../../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));

import { resetBrandingForTests } from "../../shell/branding-store";
import { WorkspaceAccessContext } from "../../workspace-access";
import { DEFAULT_FILTERS, INSIGHTS_PATH } from "./insights-data";
import { InsightsPage } from "./insights-page";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const TENANT = "00000000-0000-4000-8000-000000000004";

let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchMock = vi
    .fn()
    .mockImplementation(
      async () => new Response(JSON.stringify({}), { status: 404 }),
    );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  resetBrandingForTests();
});

async function render(role: "member" | "viewer") {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: TENANT },
          workspaces: [
            {
              tenant_id: TENANT,
              kind: "organisation",
              name: "Fictional Homes",
              role,
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        <InsightsPage
          filters={DEFAULT_FILTERS}
          view="overview"
          initial={null}
          initialCalls={null}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
}

const insightsReads = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).startsWith(INSIGHTS_PATH));

// Insights are the team's figures (roles.ts "team.view"): a Seller who follows
// a link here reads a calm line with a way back, never a 403, and nothing of
// the team's is read.
it("shows a Seller a calm line with a way back, and reads no Insights", async () => {
  await render("member");
  expect(host.textContent).toContain(
    "Only owners and managers can see Insights",
  );
  const back = [...host.querySelectorAll<HTMLAnchorElement>("a")].find(
    (link) => link.textContent === "Back to Organisation",
  );
  expect(back?.getAttribute("href")).toBe("/organisation");
  expect(
    [
      ...host.querySelectorAll<HTMLAnchorElement>(
        'nav[aria-label="Organisation"] a',
      ),
    ].map((link) => link.textContent),
  ).not.toContain("Insights");
  expect(insightsReads()).toEqual([]);
});

it("reads Insights for a Viewer, who sees the team", async () => {
  await render("viewer");
  expect(host.textContent).not.toContain(
    "Only owners and managers can see Insights",
  );
  expect(insightsReads().length).toBeGreaterThan(0);
});
