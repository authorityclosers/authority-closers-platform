// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { MePlan, Order, Plan } from "../billing/contract";
import { PlansScreen } from "./plans-screen";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("./animated-count-up", () => ({
  AnimatedCountUp: ({ targetMinutes }: { targetMinutes: number }) => (
    <div data-testid="mock-counter">+{targetMinutes} minutes</div>
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const FICTIONAL_PLANS: Plan[] = [
  {
    key: "personal",
    name: "Personal",
    audience: "For one salesperson",
    status: "active",
    prices: {
      monthlyPaise: 249900,
      yearlyPaise: 2699000,
      monthlyCents: null,
      yearlyCents: null,
    },
    includedMinutes: 800,
    seatMin: 1,
    seatMax: 1,
    perSeat: false,
    longestCallMinutes: 90,
    retentionDays: null,
    rolloverMonths: null,
    featureKeys: [],
    topUpPacks: [],
    sortOrder: 1,
    revision: 1,
  },
];
const GST_RATE = 0.18;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const text = () => host.textContent ?? "";

function fictionalMePlan(availableSeconds: number, unlimited = false): MePlan {
  return {
    plan: FICTIONAL_PLANS[0],
    longestCallSeconds: 5_400,
    allowance: {
      allowanceSeconds: 48_000,
      committedSeconds: 1_200,
      availableSeconds,
      unlimited,
    },
  };
}

function fictionalPaidOrder(minutes = 800): Order {
  return {
    orderId: "ord_fictional",
    status: "paid",
    planKey: "personal",
    planName: "Personal",
    kind: "subscription",
    account: "personal",
    mode: "test",
    interval: "month",
    seats: 1,
    amount: { minor: 249900, currency: "INR", gstInclusive: true },
    minutes,
    packKey: null,
    subscriptionId: "sub_fictional",
    createdAt: "2026-10-01T00:00:00Z",
    paidAt: "2026-10-01T00:00:00Z",
    refund: null,
  };
}

it.each([
  [0, "Current: Personal · 0 minutes left"],
  [3_540, "Current: Personal · 59 minutes left"],
  [3_600, "Current: Personal · 60 minutes left"],
  [3_659, "Current: Personal · 60 minutes left"],
  [3_660, "Current: Personal · 61 min (1 h 1 min) left"],
  [7_200, "Current: Personal · 120 min (2 h) left"],
  [48_000, "Current: Personal · 800 min (13 h 20 min) left"],
  [51_720, "Current: Personal · 862 min (14 h 22 min) left"],
  [51_745, "Current: Personal · 862 min (14 h 22 min) left"],
  [600_000, "Current: Personal · 10,000 min (166 h 40 min) left"],
])(
  "formats finite current-plan badge allowance hours (%i s)",
  async (seconds, expected) => {
    await act(async () => {
      root.render(
        <PlansScreen
          plans={FICTIONAL_PLANS}
          gstRate={GST_RATE}
          mePlan={fictionalMePlan(seconds)}
        />,
      );
    });
    expect(text()).toContain(expected);
  },
);

it("retains legacy unlimited presentation for current-plan badge", async () => {
  await act(async () => {
    root.render(
      <PlansScreen
        plans={FICTIONAL_PLANS}
        gstRate={GST_RATE}
        mePlan={fictionalMePlan(0, true)}
      />,
    );
  });
  expect(text()).toContain(
    "Current: Personal · Unlimited · 20 min used or reserved by analyses.",
  );
  expect(text()).not.toContain("minutes left");
});

it.each([
  [0, "0 analysis minutes available on your account."],
  [3_540, "59 analysis minutes available on your account."],
  [3_600, "60 analysis minutes available on your account."],
  [3_659, "60 analysis minutes available on your account."],
  [3_660, "61 min (1 h 1 min) available on your account."],
  [7_200, "120 min (2 h) available on your account."],
  [48_000, "800 min (13 h 20 min) available on your account."],
  [51_745, "862 min (14 h 22 min) available on your account."],
  [600_000, "10,000 min (166 h 40 min) available on your account."],
])(
  "formats payment-success balance hours strictly above 60 minutes (%i s)",
  async (seconds, expected) => {
    await act(async () => {
      root.render(
        <PlansScreen
          plans={FICTIONAL_PLANS}
          gstRate={GST_RATE}
          paidOrder={fictionalPaidOrder(800)}
          allowance={{
            allowanceSeconds: 48_000,
            committedSeconds: 1_200,
            availableSeconds: seconds,
            unlimited: false,
          }}
        />,
      );
    });
    expect(text()).toContain(expected);
    expect(host.querySelector('[role="status"]')?.textContent).toContain(
      expected,
    );
  },
);

it("reads allowance.availableSeconds instead of paidOrder.minutes for success balance", async () => {
  await act(async () => {
    root.render(
      <PlansScreen
        plans={FICTIONAL_PLANS}
        gstRate={GST_RATE}
        paidOrder={fictionalPaidOrder(800)}
        allowance={{
          allowanceSeconds: 48_000,
          committedSeconds: 1_200,
          availableSeconds: 51_720,
          unlimited: false,
        }}
      />,
    );
  });
  expect(text()).toContain("862 min (14 h 22 min) available on your account.");
  expect(host.querySelector('[role="status"]')?.textContent).toContain(
    "862 min (14 h 22 min) available on your account.",
  );
});

it("retains missing-balance confirming text and unlimited success balance", async () => {
  await act(async () => {
    root.render(
      <PlansScreen
        plans={FICTIONAL_PLANS}
        gstRate={GST_RATE}
        paidOrder={fictionalPaidOrder(800)}
        allowance={null}
      />,
    );
  });
  expect(text()).toContain(
    "Your updated analysis minutes are being confirmed.",
  );

  await act(async () => {
    root.render(
      <PlansScreen
        plans={FICTIONAL_PLANS}
        gstRate={GST_RATE}
        paidOrder={fictionalPaidOrder(800)}
        allowance={{
          allowanceSeconds: 48_000,
          committedSeconds: 1_200,
          availableSeconds: 0,
          unlimited: true,
        }}
      />,
    );
  });
  expect(text()).toContain("Unlimited · 20 min used or reserved by analyses.");
  expect(text()).not.toContain("available on your account.");
});
