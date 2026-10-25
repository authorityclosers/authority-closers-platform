// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

const haptic = vi.fn();
vi.mock("./haptics", () => ({ haptic: (kind: string) => haptic(kind) }));

import { AlertHost, clearAlert, raiseAlert } from "./alerts";
import { resetBackCloseForTests } from "./back-close";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(async () => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<AlertHost />));
});

afterEach(async () => {
  await act(async () => {
    clearAlert("lead");
    clearAlert("drift");
  });
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  haptic.mockClear();
  vi.useRealTimers();
});

// Owner program, 25 Oct 2026: normal is a banner up top with a light haptic.
it("shows a normal alert as a banner that leaves by itself", async () => {
  await act(async () =>
    raiseAlert({
      id: "lead",
      level: "normal",
      title: "New lead: Priya Sample",
      message: "From your Facebook form",
      action: { label: "Call", href: "/leads" },
    }),
  );
  const banner = host.querySelector('[role="status"]');
  expect(banner?.textContent).toContain("New lead: Priya Sample");
  expect(banner?.querySelector('a[href="/leads"]')?.textContent).toBe("Call");
  expect(haptic).toHaveBeenCalledWith("tap");
  await act(async () => vi.advanceTimersByTime(8_000));
  expect(host.querySelector('[role="status"]')).toBeNull();
});

it("raises the same alert again without a second buzz", async () => {
  const alert = { id: "lead", level: "normal", title: "New lead" } as const;
  await act(async () => raiseAlert(alert));
  await act(async () => raiseAlert({ ...alert, title: "2 new leads" }));
  expect(haptic).toHaveBeenCalledOnce();
  expect(host.textContent).toContain("2 new leads");
});

// Urgent: a larger card in the middle with the one thing to do.
it("shows an urgent alert as a centre card with one action and Later", async () => {
  const run = vi.fn();
  await act(async () =>
    raiseAlert({
      id: "drift",
      level: "urgent",
      title: "3 calls are late",
      message: "Rohan Example promised a call back an hour ago.",
      action: { label: "Call Rohan", run },
    }),
  );
  const card = host.querySelector('[role="alertdialog"]');
  expect(card?.getAttribute("aria-modal")).toBe("true");
  expect(card?.textContent).toContain("3 calls are late");
  expect(haptic).toHaveBeenCalledWith("urgent");
  const buttons = Array.from(card?.querySelectorAll("button") ?? []);
  expect(buttons.map((button) => button.textContent)).toEqual([
    "Call Rohan",
    "Later",
  ]);
  expect(document.activeElement).toBe(buttons[0]);
  await act(async () => buttons[0].click());
  expect(run).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="alertdialog"]')).toBeNull();
});

it("puts an urgent alert off with Escape", async () => {
  await act(async () =>
    raiseAlert({ id: "drift", level: "urgent", title: "3 calls are late" }),
  );
  await act(async () =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(host.querySelector('[role="alertdialog"]')).toBeNull();
});
