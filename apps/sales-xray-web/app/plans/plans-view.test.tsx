// @vitest-environment happy-dom
import jsQR from "jsqr";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { BillingError, type BillingClient } from "../billing/billing-api";
import { parsePlans } from "../billing/contract";
import { readAllowance } from "../dashboard/dashboard-data";
import {
  FIXTURE_PLANS,
  fixtureBilling,
  fixtureProviderReports,
  resetFixtureBilling,
} from "../review-fixture/plans/fixture-billing";
import { WorkspaceAccessContext } from "../workspace-access";
import { notify } from "../notice-center";
import { OrderReturn } from "./order-return";
import { PlansView } from "./plans-view";

const push = vi.fn();
vi.mock("../notice-center", () => ({ notify: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push,
    replace: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/plans",
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({
    children,
    showPolicyLinks,
  }: {
    children: ReactNode;
    showPolicyLinks?: boolean;
  }) => (
    <main data-policy-links={showPolicyLinks ? "true" : "false"}>
      {children}
    </main>
  ),
}));
vi.mock("../dashboard/dashboard-data", () => ({
  readAllowance: vi.fn(async () => ({
    allowance_seconds: 6000,
    committed_seconds: 2280,
    available_seconds: 3720,
  })),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  resetFixtureBilling();
  push.mockClear();
  vi.mocked(notify).mockClear();
  vi.mocked(readAllowance).mockClear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const access = (authenticated: boolean) => ({
  status: "ready" as const,
  authenticated,
  context: authenticated
    ? { personId: "p-1", sessionId: "s-1", tenantId: "t-me" }
    : null,
  retry: () => {},
});

async function render(node: ReactNode, authenticated = true) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access(authenticated)}>
        {node}
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await settle();
}

const notDeployed = () => Promise.reject(new BillingError(404, null, null));
/** A server where no billing route exists yet, apart from the catalogue. */
const comingSoon: BillingClient = {
  readPlans: async () =>
    parsePlans({
      plans: FIXTURE_PLANS.plans.map((plan) => ({
        ...plan,
        status: "coming_soon",
        prices: null,
        top_up_packs: plan.top_up_packs.map(
          ({ key, minutes, validity_rule }) => ({
            key,
            minutes,
            validity_rule,
          }),
        ),
      })),
    }),
  readMePlan: notDeployed,
  readUsage: notDeployed,
  readSubscriptions: notDeployed,
  readOfflinePayment: notDeployed,
  checkout: () =>
    Promise.reject(new BillingError(409, "not_on_sale", "Not yet.")),
  readOrder: notDeployed,
  verifyOrder: notDeployed,
  cancelSubscription: notDeployed,
};

const subscriptionCheckout = () =>
  fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "regression-subscription",
  );

const text = () => host.textContent ?? "";
const button = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) =>
      b.textContent?.trim() === label ||
      b.textContent?.trim().startsWith(`${label}save`) ||
      b.getAttribute("aria-label") === label,
  )!;
/** Lets the fictional server (250 ms a call) answer, twice over. */
const settle = async () => {
  for (let i = 0; i < 8; i += 1)
    await act(async () => new Promise((resolve) => setTimeout(resolve, 80)));
};

it("shows not-on-sale states and unknown plan/minutes when canonical reads are unavailable", async () => {
  await render(<PlansView client={comingSoon} />);
  expect(text()).toContain("Personal");
  expect(text()).toContain("Not on sale yet");
  expect(text()).not.toMatch(/₹/);
  expect(host.querySelector("[data-pay]")).toBeNull();
  expect(text()).toContain("Current plan and minutes unavailable");
  expect(text()).not.toContain("62 of 100 minutes left");
  expect(vi.mocked(readAllowance)).not.toHaveBeenCalled();
  // Enterprise asks by email; nothing is invented.
  await act(async () => button("Talk to us").click());
  expect(
    host.querySelector<HTMLAnchorElement>("[data-enterprise-send]")?.href,
  ).toMatch(/^mailto:admin@authorityclosers\.com/);
});

it("shows an unknown current subscription balance when canonical endpoints are unavailable, without reading the session", async () => {
  const checkout = await subscriptionCheckout();
  fixtureProviderReports(checkout.order.orderId, "paid");
  const readMePlan = vi.fn(notDeployed);
  await render(
    <PlansView
      client={{
        ...fixtureBilling,
        readMePlan,
        readUsage: notDeployed,
      }}
    />,
  );
  expect(text()).toContain("Personal subscription");
  expect(text()).toContain("Current plan—");
  expect(text()).toContain("Current allowance—");
  const balance = host.querySelector('[role="img"][aria-label="Minutes"]');
  expect(balance?.querySelector("b")?.textContent).toBe("—");
  expect(text()).not.toContain("62minutes left");
  expect(readMePlan).toHaveBeenCalled();
  expect(vi.mocked(readAllowance)).not.toHaveBeenCalled();
});

it("prices the approved catalogue once on sale, sums seats for a team, and starts checkout", async () => {
  await render(<PlansView client={fixtureBilling} />);
  expect(host.querySelector("[data-policy-links='true']")).not.toBeNull();
  expect(text()).toContain("₹2,499");
  expect(text()).toContain("800 analysis minutes every month");
  expect(host.querySelector("[data-pay]")?.textContent).toContain("Pay ₹2,499");

  await act(async () => button("My team").click());
  await act(async () => {});
  expect(host.querySelector("[data-plan]")?.getAttribute("data-plan")).toBe(
    "organisation",
  );
  expect(host.querySelector("output")?.textContent).toBe("3");
  expect(host.querySelector("[data-pay]")?.textContent).toContain("Pay ₹5,997");
  await act(async () => button("Add a seat").click());
  expect(host.querySelector("[data-pay]")?.textContent).toContain("Pay ₹7,996");
  expect(text()).toContain("4,000 pooled minutes a month");

  await act(async () => button("Yearly").click());
  await act(async () => {});
  // Four seats a year is above the e-mandate limit: the bank asks each time.
  expect(text()).toContain("your bank will ask you to approve each renewal");

  // Pay hands off to the hosted step (a redirect in the fixture).
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  await act(async () => button("Pay ₹79,960").click());
  await settle();
  expect(host.querySelector("[data-policy-links='true']")).not.toBeNull();
  expect(assign).toHaveBeenCalledWith(
    expect.stringMatching(/^\/review-fixture\/plans\/pay\?order=fixture-/),
  );
  vi.unstubAllGlobals();
});

it("shows the plan you are on, with cancel at period end, once the provider confirmed a payment", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "k1",
  );
  fixtureProviderReports(checkout.order.orderId, "paid");
  await render(<PlansView client={fixtureBilling} />);
  expect(text()).toContain("Personal subscription");
  expect(text()).toContain("862");
  expect(text()).toContain("Top up 100 minutes · ₹299");
  await act(async () => button("Cancel renewal").click());
  await act(async () => button("Yes, stop renewal").click());
  await settle();
  await settle();
  expect(text()).toContain("Renewal is off");
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({
      message: expect.stringContaining("recorded subscription period ends"),
    }),
  );
  expect(
    (await fixtureBilling.readSubscriptions("personal")).current
      ?.cancelAtPeriodEnd,
  ).toBe(true);
});

it("the return page only reads: awaiting → paid when the server confirms payment", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "k2",
  );
  await render(
    <OrderReturn
      orderId={checkout.order.orderId}
      client={fixtureBilling}
      plansHref="/review-fixture/plans"
    />,
  );
  expect(text()).toContain("Confirming your payment");
  fixtureProviderReports(checkout.order.orderId, "paid");
  // The page polls every 3 s.
  for (let i = 0; i < 45; i += 1)
    await act(async () => new Promise((resolve) => setTimeout(resolve, 80)));
  expect(text()).toContain("Payment confirmed");
  expect(text()).toContain("₹2,499");

  await act(async () => root.unmount());
  root = createRoot(host);
  const failed = await fixtureBilling.checkout(
    {
      kind: "top_up",
      account: "personal",
      planKey: "personal",
      packKey: "personal_100",
    },
    "k3",
  );
  fixtureProviderReports(failed.order.orderId, "failed");
  await render(
    <OrderReturn orderId={failed.order.orderId} client={fixtureBilling} />,
  );
  expect(text()).toContain("Payment failed");
  expect(text()).not.toContain("No money was taken");
}, 15_000);

it("reads the order result after SDK dismissal without claiming a bank outcome", async () => {
  const script = document.createElement("script");
  script.type = "text/plain"; // No provider script or network request in this fixture.
  script.src = "https://checkout.razorpay.com/v1/checkout.js";
  script.dataset.loaded = "true";
  document.head.append(script);
  vi.stubGlobal(
    "Razorpay",
    class {
      constructor(private options: { modal: { ondismiss: () => void } }) {}
      open() {
        this.options.modal.ondismiss();
      }
    },
  );
  try {
    await render(
      <PlansView
        client={{
          ...fixtureBilling,
          checkout: async (...args) => ({
            ...(await fixtureBilling.checkout(...args)),
            hosted: {
              kind: "client_sdk",
              provider: "razorpay",
              url: null,
              params: {},
              expiresAt: "2030-01-01T00:00:00Z",
            },
          }),
        }}
      />,
    );
    await act(async () => button("Pay ₹2,499").click());
    await settle();
    expect(push).toHaveBeenCalledWith(
      expect.stringMatching(/^\/account\/billing\/return\?order=fixture-/),
    );
    expect(text()).not.toMatch(
      /No money was taken|Payment not completed|try again whenever/,
    );
  } finally {
    script.remove();
    vi.unstubAllGlobals();
  }
});

it.each(["failed", "expired"] as const)(
  "shows %s without promising no debit or advising an immediate retry",
  async (status) => {
    const checkout = await subscriptionCheckout();
    await render(
      <OrderReturn
        orderId={checkout.order.orderId}
        client={{
          ...fixtureBilling,
          readOrder: async () => ({ ...checkout.order, status }),
        }}
      />,
    );
    expect(text()).toContain(
      status === "failed" ? "Payment failed" : "Order expired",
    );
    expect(text()).toContain("If your bank shows a debit, check its status");
    expect(text()).not.toMatch(/No money was taken|try again whenever/);
  },
);

it.each([
  ["pending_authorisation", "Waiting for your bank"],
  ["past_due", "Payment due"],
  ["halted", "Paused"],
] as const)(
  "labels a %s subscription without treating it as access",
  async (status, label) => {
    const checkout = await subscriptionCheckout();
    fixtureProviderReports(checkout.order.orderId, "paid");
    const { current } = await fixtureBilling.readSubscriptions("personal");
    const me = await fixtureBilling.readMePlan();
    await render(
      <PlansView
        client={{
          ...fixtureBilling,
          readSubscriptions: async () => ({
            current: { ...current!, status },
            past: [],
          }),
          readMePlan: async () => ({
            ...me,
            plan: { key: "trial", name: "Trial" },
            allowance: {
              unlimited: false,
              allowanceSeconds: 6000,
              committedSeconds: 6000,
              availableSeconds: 0,
            },
          }),
        }}
      />,
    );
    expect(host.querySelector(`[data-status="${status}"]`)?.textContent).toBe(
      label,
    );
    expect(text()).toContain("Current planTrial");
    expect(text()).toContain("0minutes left");
    expect(text()).not.toMatch(
      /Plan active|Your minutes are ready|You are on Personal/,
    );
  },
);

it.each(["unavailable", "zero"] as const)(
  "shows a historical paid receipt with %s current balance without granting minutes",
  async (balance) => {
    const checkout = await subscriptionCheckout();
    fixtureProviderReports(checkout.order.orderId, "paid");
    const topUp = await fixtureBilling.checkout(
      {
        kind: "top_up",
        account: "personal",
        planKey: "personal",
        packKey: "personal_100",
      },
      "historical-top-up",
    );
    const order = balance === "zero" ? topUp.order : checkout.order;
    const me = await fixtureBilling.readMePlan();
    const readMePlan = vi.fn(
      balance === "unavailable"
        ? notDeployed
        : async () => ({
            ...me,
            allowance: {
              unlimited: false,
              allowanceSeconds: 0,
              committedSeconds: 0,
              availableSeconds: 0,
            },
          }),
    );
    await render(
      <OrderReturn
        orderId={order.orderId}
        client={{
          ...fixtureBilling,
          readMePlan,
          readOrder: async () => ({
            ...order,
            status: "paid",
            paidAt: "2020-01-01T00:00:00Z",
          }),
        }}
      />,
    );
    expect(text()).toContain("Payment confirmed");
    expect(text()).toContain("Order minutes");
    expect(text()).not.toMatch(/Your minutes are ready|Top-up added/);
    expect(readMePlan).not.toHaveBeenCalled(); // A receipt does not claim a current balance.
  },
);

it("encodes the displayed fictional offline payee and UPI ID locally, retaining not-on-sale", async () => {
  const offline = {
    ...(await fixtureBilling.readOfflinePayment()),
    upiId: "fictional+pay@upi",
    payeeName: "Fictional & Payee",
  };
  await render(
    <PlansView
      client={{ ...comingSoon, readOfflinePayment: async () => offline }}
    />,
  );
  const uri =
    "upi://pay?pa=fictional%2Bpay%40upi&pn=Fictional%20%26%20Payee&cu=INR";
  expect(text()).toContain(offline.upiId);
  expect(text()).toContain(offline.payeeName);
  expect(text()).toContain("Not on sale yet");
  expect(
    host
      .querySelector<HTMLAnchorElement>('a[href^="upi:"]')
      ?.getAttribute("href"),
  ).toBe(uri);
  const svg = host.querySelector<SVGSVGElement>(
    'svg[aria-label="Scan to pay by UPI"]',
  )!;
  // Rasterise the rendered SVG's black module runs; decode with a separate reader.
  const modules = Number(svg.getAttribute("viewBox")!.split(" ")[2]);
  const size = modules * 8;
  const pixels = new Uint8ClampedArray(size * size * 4).fill(255);
  const path = svg.querySelector('path[fill="#000000"]')!.getAttribute("d")!;
  for (const match of path.matchAll(/M(\d+)[ ,](\d+)\s*h(\d+)v1H\d+z/g)) {
    const [, x, y, width] = match.map(Number);
    for (let row = y * 8; row < (y + 1) * 8; row++)
      for (let col = x * 8; col < (x + width) * 8; col++)
        pixels.fill(0, (row * size + col) * 4, (row * size + col) * 4 + 3);
  }
  expect(jsQR(pixels, size, size)?.data).toBe(uri);
});

it("keeps bank-only offline details usable without a UPI QR", async () => {
  const offline = {
    ...(await fixtureBilling.readOfflinePayment()),
    upiId: null,
  };
  await render(
    <PlansView
      client={{ ...comingSoon, readOfflinePayment: async () => offline }}
    />,
  );
  expect(text()).toContain("Fictional Bank");
  expect(host.querySelector('svg[aria-label="Scan to pay by UPI"]')).toBeNull();
  expect(host.querySelector('a[href^="upi:"]')).toBeNull();
});

it("asks a signed-out visitor to sign in instead of paying", async () => {
  await render(<PlansView client={fixtureBilling} />, false);
  expect(host.querySelector("[data-pay]")?.textContent).toContain(
    "Sign in to pay",
  );
  await act(async () => button("Sign in to pay").click());
  expect(push).toHaveBeenCalledWith("/login");
});
