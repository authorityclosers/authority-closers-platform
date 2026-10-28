// @vitest-environment happy-dom
import { webcrypto } from "node:crypto";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "./page";
import { LoginForm } from "../components/login-form";
import {
  HANDOFF_VERIFIER_KEY,
  handoffChallenge,
} from "../lib/cross-app-handoff";
import * as places from "../shell/places";
import * as bridge from "../lib/dev-api-proxy";
import ConsentPage from "../(app)/consent/renewal/page";

vi.mock("../shell/screen-title", () => ({ ScreenTitle: () => null }));
vi.mock("../components/consent-renewal-runtime", () => ({
  ConsentRenewalRuntime: ({ returnHref }: { returnHref: string }) => (
    <span data-return={returnHref} />
  ),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  vi.spyOn(bridge, "isStagingAuthenticatedBridge").mockReturnValue(false);
  window.history.replaceState({}, "", "/login");
  sessionStorage.clear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function mount(content: ReactNode | Promise<ReactNode>) {
  const resolved = await content;
  await act(async () => root.render(resolved));
}
function knownHost() {
  vi.spyOn(places, "salesXrayForHost").mockReturnValue(
    "https://salesxray.authorityclosers.com",
  );
}
it("has one heading, Sales then Google then email, and recovery/registration links", async () => {
  knownHost();
  await mount(Page({ searchParams: Promise.resolve({}) }));
  expect(
    [...container.querySelectorAll("h1,h2")].map((node) => node.textContent),
  ).toEqual(["Sign in to Reflex"]);
  const text = container.textContent!;
  expect(text.indexOf("Continue with Sales X-Ray")).toBeLessThan(
    text.indexOf("Continue with Google"),
  );
  expect(text.indexOf("Continue with Google")).toBeLessThan(
    text.indexOf("Email address"),
  );
  expect(text).toContain("Sales training by Authority Closers");
  expect(text).not.toContain("staging");
  expect(text).not.toContain("Welcome back");
  expect(container.querySelector('a[href="/forgot-password"]')).not.toBeNull();
  expect(container.querySelector('a[href="/register"]')).not.toBeNull();
  expect(container.querySelector("svg")).not.toBeNull();
  expect(
    container.querySelector('input[name="email"]')?.hasAttribute("required"),
  ).toBe(true);
});
it("hides cross-app sign-in on unknown/local hosts", async () => {
  expect(places.salesXrayForHost(window.location.hostname)).toBeNull();
  await mount(<LoginForm />);
  expect(container.textContent).not.toContain("Continue with Sales X-Ray");
  expect(container.textContent).toContain("Continue with Google");
});
it("stores a fresh verifier and navigates with only its challenge and intended return", async () => {
  knownHost();
  vi.stubGlobal("crypto", webcrypto);
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => {});
  await mount(
    Page({ searchParams: Promise.resolve({ next: "/learning?tab=mine" }) }),
  );
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('button[data-variant="primary"]')!
      .click(),
  );
  // WebCrypto completion runs outside React's microtask queue.
  await vi.waitFor(() => expect(assign).toHaveBeenCalledTimes(1));
  const verifier = sessionStorage.getItem(HANDOFF_VERIFIER_KEY)!;
  const url = new URL(assign.mock.calls[0][0] as string);
  expect(verifier).toMatch(/^[A-Za-z0-9_-]{43}$/);
  expect(url.origin + url.pathname).toBe(
    "https://salesxray.authorityclosers.com/connect/reflex",
  );
  expect(url.searchParams.get("challenge")).toBe(
    await handoffChallenge(verifier),
  );
  expect(url.searchParams.get("return")).toBe("/learning?tab=mine");
  expect(url.href).not.toContain(verifier);
});
it("shows the expired handoff as a dismissible calm corner card", async () => {
  await mount(Page({ searchParams: Promise.resolve({ handoff: "expired" }) }));
  expect(
    container.querySelector('aside[role="status"]')?.textContent,
  ).toContain("This sign-in link has expired.");
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(
        'button[aria-label="Dismiss sign-in message"]',
      )!
      .click(),
  );
  expect(container.querySelector("aside")).toBeNull();
});
it("carries a validated return through the existing consent renewal route", async () => {
  await mount(
    ConsentPage({
      searchParams: Promise.resolve({ return: "/activity/example?tab=notes" }),
    }),
  );
  expect(
    container.querySelector("[data-return]")?.getAttribute("data-return"),
  ).toBe("/activity/example?tab=notes");
});
it.each(["//evil.test", "https://evil.test", "/\\evil.test"])(
  "consent never follows unsafe return %s",
  async (value) => {
    await mount(
      ConsentPage({ searchParams: Promise.resolve({ return: value }) }),
    );
    expect(
      container.querySelector("[data-return]")?.getAttribute("data-return"),
    ).toBe("/home");
  },
);
