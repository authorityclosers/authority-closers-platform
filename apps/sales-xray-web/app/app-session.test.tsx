// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppSession } from "./app-session";
import PlansPage from "./plans/page";
import { useWorkspaceAccess } from "./workspace-access";

let pathname = "/plans";
const push = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const identity = {
  person_id: "fictional-person",
  session_id: "fictional-session",
  selected_tenant_id: "fictional-tenant",
  workspaces: [{ tenant_id: "fictional-tenant", name: "Personal" }],
};
const directory = {
  selected_tenant_id: "fictional-tenant",
  workspaces: [
    {
      tenant_id: "fictional-tenant",
      name: "Personal",
      kind: "personal",
      role: null,
      sales_xray_enabled: true,
    },
  ],
};
const hostedUrl =
  "https://fictional.example/checkout?token=fictional%2Bopaque&return=fictional%2Freturn";
const checkout = {
  order: {
    order_id: "fictional-order",
    kind: "subscription",
    account: "personal",
    status: "awaiting_payment",
    mode: "test",
    amount: { minor: 249900, currency: "INR", gst_inclusive: true },
    plan_key: "personal",
    plan_name: "Personal",
    interval: "month",
    seats: 1,
    pack_key: null,
    minutes: 800,
    subscription_id: null,
    created_at: "2026-10-04T00:00:00Z",
    paid_at: null,
    refund: null,
  },
  hosted: {
    provider: "fake",
    kind: "redirect",
    url: hostedUrl,
    params: {},
    expires_at: null,
  },
};
let host: HTMLDivElement;
let root: Root;
let fetchMock: ReturnType<typeof vi.fn>;
let assign: ReturnType<typeof vi.spyOn>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
const paths = () => fetchMock.mock.calls.map(([path]) => path);
const click = async (label: string) => {
  const button = [...host.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === label,
  );
  expect(button).toBeDefined();
  await act(async () => button!.click());
};
const mount = async (child = <PlansPage />) => {
  await act(async () => root.render(<AppSession>{child}</AppSession>));
};
const expectFocusedShell = () => {
  expect(host.querySelector("[data-purchase-shell]")).not.toBeNull();
  expect(
    host.querySelector(
      'aside, [data-shell-toolbar], nav[aria-label="Mobile Sales Xray navigation"]',
    ),
  ).toBeNull();
};

beforeEach(() => {
  pathname = "/plans";
  push.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  assign = vi.spyOn(window.location, "assign").mockImplementation(() => {});
  fetchMock = vi.fn(async (path: string) => {
    if (path === "/v1/me/workspaces") return json(identity);
    if (path === "/v1/me/sales-xray-workspaces") return json(directory);
    if (path === "/v1/checkout") return json(checkout);
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it.each(["/plans", "/plans/"])(
  "bootstraps actual %s before preparing and opening fictional checkout",
  async (route) => {
    pathname = route;
    await mount();
    expect(paths().slice(0, 2)).toEqual([
      "/v1/me/workspaces",
      "/v1/me/sales-xray-workspaces",
    ]);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
    expectFocusedShell();
    await click("Get Personal");
    await click("Review total with Razorpay");
    const orders = fetchMock.mock.calls.filter(
      ([path]) => path === "/v1/checkout",
    );
    expect(orders).toHaveLength(1);
    expect(orders[0][1]).toMatchObject({
      method: "POST",
      headers: { "Idempotency-Key": expect.any(String) },
    });
    expect(JSON.parse(orders[0][1].body)).toEqual({
      kind: "subscription",
      account: "personal",
      plan_key: "personal",
      interval: "month",
      seats: 1,
    });
    expect(host.textContent).toContain("Test payment · no money moves");
    expect(assign).not.toHaveBeenCalled();
    expectFocusedShell();
    await click("Continue to test payment");
    expect(assign).toHaveBeenCalledExactlyOnceWith(hostedUrl);
    expect(push).not.toHaveBeenCalled();
  },
);

it("retains signed-out plans sign-in without preparing an order", async () => {
  fetchMock.mockResolvedValueOnce(json({}, 401));
  await mount();
  expectFocusedShell();
  await click("Get Personal");
  await click("Review total with Razorpay");
  expect(push).toHaveBeenCalledExactlyOnceWith("/login?returnTo=%2Fplans");
  expect(paths()).not.toContain("/v1/checkout");
  expect(paths()).not.toContain("/v1/me/sales-xray-workspaces");
  expect(assign).not.toHaveBeenCalled();
});

it("withholds checkout while the session is pending", async () => {
  let resolve!: (response: Response) => void;
  fetchMock.mockReturnValueOnce(
    new Promise<Response>((done) => {
      resolve = done;
    }),
  );
  await mount();
  expect(host.textContent).toContain("Checking your account…");
  expect(host.textContent).not.toContain("Get Personal");
  expectFocusedShell();
  await act(async () => resolve(json(identity)));
  await click("Get Personal");
  await click("Review total with Razorpay");
  expect(paths()).toContain("/v1/checkout");
});

it.each(["identity", "directory"])(
  "fails closed on invalid %s and retries the bootstrap",
  async (invalid) => {
    fetchMock.mockResolvedValueOnce(
      json(invalid === "identity" ? {} : identity),
    );
    if (invalid === "directory")
      fetchMock.mockResolvedValueOnce(
        json({ ...directory, selected_tenant_id: "unknown-tenant" }),
      );
    await mount();
    expect(host.textContent).toContain("Workspace access could not be checked");
    expect(host.textContent).not.toContain("Get Personal");
    expect(paths()).not.toContain("/v1/checkout");
    expectFocusedShell();
    await click("Try again");
    await click("Get Personal");
    await click("Review total with Razorpay");
    expect(paths()).toContain("/v1/checkout");
  },
);

function AccountProbe() {
  const access = useWorkspaceAccess();
  return <output>{JSON.stringify(access?.context)}</output>;
}
it("keeps account routes inside the existing authenticated app boundary", async () => {
  pathname = "/account/";
  await mount(<AccountProbe />);
  expect(JSON.parse(host.querySelector("output")!.textContent!)).toEqual({
    personId: identity.person_id,
    sessionId: identity.session_id,
    tenantId: directory.selected_tenant_id,
  });
  expect(
    host.querySelector('aside[aria-label="Sales Xray navigation"]'),
  ).not.toBeNull();
  expect(host.querySelector("[data-purchase-shell]")).toBeNull();
});
it("keeps login and fixture routes outside both session boundaries", async () => {
  for (const route of ["/login/", "/review-fixture/plans"]) {
    pathname = route;
    await mount(<p>Public route</p>);
    expect(host.textContent).toBe("Public route");
  }
  expect(fetchMock).not.toHaveBeenCalled();
});
