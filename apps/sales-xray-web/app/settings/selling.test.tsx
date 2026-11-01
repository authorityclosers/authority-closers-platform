import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { readMe, type Desk } from "../leads/leads-client";
import { SellingSettings } from "./selling";

vi.mock("../leads/leads-client", () => ({ readMe: vi.fn() }));
vi.mock("../call-ai/call-ai-client", () => ({
  readCallAi: vi.fn(async () => {
    throw new Error("offline");
  }),
}));
vi.mock("../leads/native-phone", async (original) => ({
  ...(await original<typeof import("../leads/native-phone")>()),
  inPhoneApp: () => true,
}));
vi.mock("../leads/alerts-card", () => ({ AlertsCard: () => null }));
vi.mock("../leads/phone-log-card", () => ({ PhoneLogCard: () => null }));
vi.mock("../leads/taking-switch", () => ({ TakingSwitch: () => null }));
vi.mock("./company-calling", () => ({ CompanyCallingPanel: () => null }));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let host: HTMLDivElement;

async function render(manager: boolean) {
  vi.mocked(readMe).mockResolvedValue({
    person_id: "person",
    name: "Asha Fictional",
    role: manager ? "owner" : "member",
    can_manage: manager,
    taking_leads: true,
  } as Desk["me"]);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(<SellingSettings />);
  });
}

afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
  vi.clearAllMocks();
});

it("tells an owner where seller limits are set, with the way there", async () => {
  await render(true);
  // Phone personas ph1-37 (1 Nov 2026): "Leads → Team" doesn't exist.
  expect(host.textContent).not.toContain("Leads → Team");
  const link = host.querySelector<HTMLAnchorElement>(
    'a[href="/organisation?tab=leads&part=rules"]',
  );
  expect(link?.textContent).toBe("Leads setup → Lead rules → Seller rules");
});

it("tells a seller their owner or admin sets them, with no path they can't open", async () => {
  await render(false);
  expect(host.textContent).toContain(
    "how many open leads you hold are set by your owner or admin.",
  );
  expect(host.querySelector('a[href^="/organisation"]')).toBeNull();
});

it("opens the checked-list setup from Phone setup's Set up", async () => {
  await render(false);
  const asked: unknown[] = [];
  const listen = (event: Event) =>
    asked.push((event as CustomEvent<unknown>).detail);
  window.addEventListener("sx-capture-setup-open", listen);
  const button = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Set up",
  );
  await act(async () => button?.click());
  window.removeEventListener("sx-capture-setup-open", listen);
  // From the top, never at a step: Settings runs the whole list again.
  expect(asked).toEqual([null]);
});
