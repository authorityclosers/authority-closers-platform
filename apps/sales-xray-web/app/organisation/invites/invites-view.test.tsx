// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SELECT_WORKSPACE_EVENT } from "../../call-ownership";
import { resetInvitesForTests } from "../../shell/invites-store";
import { WorkspaceAccessContext } from "../../workspace-access";
import { InvitesView } from "./invites-view";

vi.mock("../../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
const notices = vi.hoisted(() => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
vi.mock("../../notice-center", () => notices);
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const personId = "00000000-0000-4000-8000-000000000001";
const inviteId = "00000000-0000-4000-8000-000000000002";
const otherInvite = "00000000-0000-4000-8000-000000000005";
const tenantId = "00000000-0000-4000-8000-000000000003";
const row = {
  invite_id: inviteId,
  tenant_id: tenantId,
  organisation_name: "Brightline Coaching",
  role: "member",
  invited_at: "2026-10-10T09:00:00Z",
  expires_at: "2026-10-17T09:00:00Z",
};
let root: Root;
let host: HTMLDivElement;
let invites: { status: number; body: unknown };
let accept: { status: number; body: unknown };
let fetchMock: ReturnType<typeof vi.fn>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

beforeEach(() => {
  resetInvitesForTests();
  notices.notify.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  invites = { status: 200, body: { invites: [row] } };
  accept = {
    status: 200,
    body: {
      invite_id: inviteId,
      tenant_id: tenantId,
      person_id: personId,
      role: "member",
      status: "accepted",
    },
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/v1/organisation/invites") {
      return json(invites.body, invites.status);
    }
    if (path.endsWith("/accept") && init?.method === "POST")
      return json(accept.body, accept.status);
    if (path === "/v1/me/sales-xray-profile")
      return json({ detail: "Not Found" }, 404);
    return json({ detail: "Not Found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function render(id: string | null, authenticated = true) {
  const signIn = vi.fn();
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: authenticated ? "ready" : "unauthenticated",
          authenticated,
          context: authenticated
            ? { personId, sessionId: "s-1", tenantId: "personal" }
            : null,
          retry: () => {},
          requestAccountSignIn: signIn,
        }}
      >
        <InvitesView inviteId={id} />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await act(async () => {});
  return signIn;
}
const buttons = () => [...host.querySelectorAll<HTMLButtonElement>("button")];

it("joins the invitation from the email link and opens the organisation", async () => {
  invites.body = {
    invites: [
      { ...row, invite_id: otherInvite, organisation_name: "Other" },
      row,
    ],
  };
  const moved = vi.fn();
  window.addEventListener(SELECT_WORKSPACE_EVENT, moved);
  await render(inviteId);
  // The linked invitation leads and alone carries the primary button.
  const rows = [...host.querySelectorAll("li")];
  expect(rows[0].textContent).toContain("Brightline Coaching");
  expect(rows[0].textContent).toContain("Invited as seller");
  expect(rows[0].textContent).toContain("Open until");
  const join = rows[0].querySelector("button")!;
  expect(join.getAttribute("data-variant")).toBe("primary");
  expect(rows[1].querySelector("button")!.getAttribute("data-variant")).toBe(
    "secondary",
  );
  await act(async () => join.click());
  await act(async () => {});
  const [url, init] = fetchMock.mock.calls.find(([path]) =>
    String(path).endsWith("/accept"),
  ) as [string, RequestInit];
  expect(url).toBe(`/v1/organisation/invites/${inviteId}/accept`);
  expect(new Headers(init.headers).get("Idempotency-Key")).toMatch(
    /^[\da-f]{8}-[\da-f]{4}-4/,
  );
  expect(moved).toHaveBeenCalledTimes(1);
  expect((moved.mock.calls[0][0] as CustomEvent).detail).toEqual({
    tenantId,
    next: "/organisation",
  });
  // While the shell moves (or if its move fails), the page says so and
  // offers the organisation again; nothing is left spinning.
  expect(host.textContent).toContain("You joined Brightline Coaching");
  await act(async () =>
    buttons()
      .find((button) => button.textContent === "Open Brightline Coaching")!
      .click(),
  );
  expect(moved).toHaveBeenCalledTimes(2);
  window.removeEventListener(SELECT_WORKSPACE_EVENT, moved);
});

it("says plainly when the linked invitation isn't open for this account", async () => {
  invites.body = { invites: [] };
  await render(inviteId);
  expect(host.querySelector('[role="status"]')?.textContent).toContain(
    "That invitation isn’t open for this account",
  );
  expect(host.textContent).toContain("No invitations waiting");
  expect(buttons()).toHaveLength(0);
});

it("keeps the invitation and offers a retry when joining fails", async () => {
  accept = { status: 503, body: { detail: "Try again in a moment." } };
  await render(inviteId);
  await act(async () => buttons()[0].click());
  await act(async () => {});
  const notice = notices.notify.mock.calls[0][0];
  expect(notice.title).toBe("Couldn’t join Brightline Coaching");
  expect(notice.action?.label).toBe("Try again");
  expect(buttons()[0].disabled).toBe(false);
  expect(host.textContent).toContain("Brightline Coaching");
});

it("asks a signed-out visitor to sign in with the invited email", async () => {
  const signIn = await render(inviteId, false);
  expect(host.textContent).toContain("Sign in to answer your invitation");
  await act(async () => buttons()[0].click());
  expect(signIn).toHaveBeenCalledTimes(1);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("offers nothing it can't keep where the server has no invitations", async () => {
  invites = { status: 404, body: { detail: "Not Found" } };
  await render(inviteId);
  expect(host.textContent).toContain("Invitations aren’t available here yet");
  expect(buttons()).toHaveLength(0);
});
