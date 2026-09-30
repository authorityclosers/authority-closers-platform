// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessContext } from "../workspace-access";
import { OrganisationView } from "./organisation-view";

vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let routes: Record<string, unknown>;
let fetchMock: ReturnType<typeof vi.fn>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  routes = {
    "/v1/me/workspaces": {
      person_id: "p-1",
      session_id: "s-1",
      selected_tenant_id: "t-org",
      workspaces: [
        { tenant_id: "t-me", name: "Authority Closers Public Learners" },
        { tenant_id: "t-org", name: "Authority Closers" },
      ],
    },
    "/v1/context": { membership_role: "owner", permissions: [] },
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") return json({}, 201);
    const url = String(path);
    return url in routes
      ? json(routes[url])
      : json({ detail: "Not Found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function render() {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p-1", sessionId: "s-1", tenantId: "t-org" },
          retry: () => {},
        }}
      >
        <OrganisationView />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await act(async () => {});
}

const tab = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("nav button")].find(
    (button) => button.textContent === name,
  )!;

it("marks unavailable organisation features as coming soon", async () => {
  await render();
  expect(host.querySelector("h1")?.textContent).toBe("Authority Closers");
  expect(host.textContent).toContain("Coming soon.");
  expect(host.textContent).not.toMatch(/AUT-\d+/);
  await act(async () => tab("Members").click());
  expect(host.querySelectorAll('[role="row"]')).toHaveLength(2);
  expect(
    host.querySelector<HTMLInputElement>('input[aria-label="Email to add"]')
      ?.disabled,
  ).toBe(true);
});

it("lists members and adds a person by email once the API is live", async () => {
  routes["/v1/organisation"] = {
    tenant_id: "t-org",
    name: "Authority Closers",
    role: "owner",
    verified_domains: ["example.com"],
    auto_join: true,
    member_count: 2,
  };
  routes["/v1/organisation/members"] = {
    members: [
      {
        person_id: "p-1",
        name: "Admin",
        email: "admin@example.com",
        role: "owner",
        status: "active",
        minutes_used_30d: 12,
        calls_30d: 3,
      },
      {
        person_id: "p-2",
        name: "Dipak",
        email: "alex@example.com",
        role: "member",
        status: "invited",
        minutes_used_30d: 0,
        calls_30d: 0,
      },
    ],
  };
  await render();
  expect(host.textContent).toContain("2 people");
  await act(async () => tab("Members").click());
  expect(host.textContent).toContain("alex@example.com");
  expect(host.textContent).toContain("Invited");
  const input = host.querySelector<HTMLInputElement>(
    'input[aria-label="Email to add"]',
  )!;
  expect(input.disabled).toBe(false);
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "new.member@example.com");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  const post = fetchMock.mock.calls.find(
    ([, init]) => (init as RequestInit | undefined)?.method === "POST",
  )!;
  expect(post[0]).toBe("/v1/organisation/members");
  expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({
    email: "new.member@example.com",
    role: "member",
  });

  await act(async () => tab("Company").click());
  expect(host.textContent).toContain("@example.com");
});

it("shows the personal account card when no organisation is selected", async () => {
  (
    routes["/v1/me/workspaces"] as { selected_tenant_id: string }
  ).selected_tenant_id = "t-me";
  await render();
  expect(host.textContent).toContain("You are on your personal account");
  expect(host.textContent).toContain("Switch to Authority Closers");
});
