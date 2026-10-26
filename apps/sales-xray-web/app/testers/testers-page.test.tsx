import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { TESTERS, whatsappLink } from "./testers-config";
import { COPY, LANGS } from "./testers-copy";
import { TestersPage } from "./testers-page";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Tester programme (26 Oct 2026): three steps, the links from one config,
// English, Hindi and Marathi, nothing kept but reminders on this device.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/testers");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const steps = () =>
  [...host.querySelectorAll<HTMLAnchorElement>("a[data-step]")].map((link) => ({
    step: link.dataset.step,
    href: link.getAttribute("href"),
    text: link.textContent,
    blank: link.target === "_blank",
  }));

it("points the three buttons at the configured links", async () => {
  await act(async () => root.render(<TestersPage />));
  expect(steps()).toEqual([
    { step: "1", href: TESTERS.groupUrl, text: "Join the group", blank: true },
    { step: "2", href: TESTERS.optInUrl, text: "Become a tester", blank: true },
    {
      step: "3",
      href: TESTERS.playUrl,
      text: "Open in Google Play",
      blank: true,
    },
  ]);
  // No help group configured yet: no "Still stuck?" line.
  expect(host.textContent).not.toContain("Still stuck?");
  // No prices on this page.
  expect(host.textContent).not.toMatch(/₹|Rs\.?\s?\d/);
});

it("sends the Gmail on WhatsApp on the WhatsApp route, and offers help when configured", async () => {
  await act(async () =>
    root.render(
      <TestersPage
        config={{
          ...TESTERS,
          route: "whatsapp",
          whatsappNumber: "910000000000",
          helpUrl: "https://chat.whatsapp.com/example",
        }}
      />,
    ),
  );
  expect(steps()[0]).toEqual({
    step: "1",
    href: whatsappLink("910000000000", COPY.en.gmailMessage),
    text: "Send my Gmail on WhatsApp",
    blank: true,
  });
  expect(
    host.querySelector('a[href="https://chat.whatsapp.com/example"]')
      ?.textContent,
  ).toBe("Ask on WhatsApp");
});

it("changes every line when the language changes, and keeps the choice", async () => {
  await act(async () => root.render(<TestersPage />));
  expect(host.querySelector("h1")?.textContent).toBe(COPY.en.title);
  const english = host.textContent;
  const marathi = [
    ...host.querySelectorAll<HTMLButtonElement>("button[lang]"),
  ].find((button) => button.textContent === "मराठी")!;
  await act(async () => marathi.click());
  expect(host.querySelector("h1")?.textContent).toBe(COPY.mr.title);
  expect(marathi.getAttribute("aria-pressed")).toBe("true");
  expect(localStorage.getItem("sx.testers.lang")).toBe("mr");
  expect(new URLSearchParams(window.location.search).get("lang")).toBe("mr");
  // Every step and every "Stuck?" line follows.
  for (const line of [
    COPY.mr.groupTitle,
    COPY.mr.optInTitle,
    COPY.mr.installTitle,
    COPY.mr.stayText,
    ...COPY.mr.stuck.map((item) => item.q),
  ])
    expect(host.textContent).toContain(line);
  expect(host.textContent).not.toBe(english);
  // Each language has the same lines.
  for (const { key } of LANGS) {
    expect(Object.keys(COPY[key]).sort()).toEqual(Object.keys(COPY.en).sort());
    expect(COPY[key].stuck).toHaveLength(COPY.en.stuck.length);
  }
});

it("ticks a step as done, as a reminder on this device", async () => {
  await act(async () => root.render(<TestersPage />));
  const done = host.querySelectorAll<HTMLButtonElement>(
    "button[aria-pressed]:not([lang])",
  );
  expect(done).toHaveLength(3);
  await act(async () => done[1].click());
  expect(done[1].getAttribute("aria-pressed")).toBe("true");
  expect(JSON.parse(localStorage.getItem("sx.testers.done") ?? "[]")).toEqual([
    2,
  ]);
});
