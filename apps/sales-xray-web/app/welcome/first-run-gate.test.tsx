// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../dashboard/dashboard-data", () => ({
  readCallSummary: async () => ({ total: 4 }),
}));

import { WorkspaceAccessContext } from "../workspace-access";
import { FirstRunGate } from "./first-run-gate";
import { FIRST_RUN_ATTRIBUTE, noteFreshSignIn, PICK_PATH } from "./setup-state";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const PERSON = "00000000-0000-4000-8000-000000000001";
const workspace = (tenant: string, kind: "personal" | "organisation") => ({
  tenant_id: tenant,
  kind,
  name: kind === "personal" ? "Personal" : "Fictional Homes",
  role: kind === "personal" ? null : ("member" as const),
  sales_xray_enabled: true,
});

let root: Root;
let host: HTMLDivElement;
let replace: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  replace = vi
    .spyOn(window.location, "replace")
    .mockImplementation(() => undefined);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  document.documentElement.removeAttribute(FIRST_RUN_ATTRIBUTE);
  vi.restoreAllMocks();
});

async function mount(workspaces: ReturnType<typeof workspace>[]) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: PERSON, sessionId: "s", tenantId: "t" },
          workspaces,
          retry: () => {},
        }}
      >
        <FirstRunGate />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await act(async () => Promise.resolve());
}

// Owner, 25 Oct 2026: where to work is asked right after a sign-in, and the
// phone setup waits meanwhile (one flow, one screen at a time).
it("asks where to work after a sign-in with two workspaces", async () => {
  noteFreshSignIn();
  await mount([workspace("a", "personal"), workspace("b", "organisation")]);
  expect(replace).toHaveBeenCalledWith(PICK_PATH);
  expect(document.documentElement.hasAttribute(FIRST_RUN_ATTRIBUTE)).toBe(true);
});

it("lets the phone setup go on when there is nothing to ask", async () => {
  noteFreshSignIn();
  await mount([workspace("b", "organisation")]);
  expect(replace).not.toHaveBeenCalled();
  expect(document.documentElement.hasAttribute(FIRST_RUN_ATTRIBUTE)).toBe(
    false,
  );
});

it("asks nothing on a later visit", async () => {
  await mount([workspace("a", "personal"), workspace("b", "organisation")]);
  expect(replace).not.toHaveBeenCalled();
});
