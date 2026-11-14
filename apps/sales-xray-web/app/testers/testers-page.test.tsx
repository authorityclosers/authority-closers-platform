import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { TESTERS } from "./testers-config";
import {
  isAndroidBrowser,
  parseTesterMe,
  SIGN_IN,
  type TesterMe,
} from "./testers-client";
import { TestersPage } from "./testers-page";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Tester programme v2 (owner, 13 Nov 2026): one button to sign in, three
// fields to join, then Play's two steps once the team has added the account.
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
  vi.unstubAllGlobals();
});

const me = (state: TesterMe["state"]): TesterMe => ({
  state,
  email: "ravi.tester@gmail.com",
  phoneModel: null,
  listed: false,
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

it("shows one headline, one line and one button that signs in and comes back", async () => {
  await act(async () => root.render(<TestersPage initial="signed_out" />));
  expect(host.querySelectorAll("h1")).toHaveLength(1);
  const cta = host.querySelector<HTMLAnchorElement>("a[data-testers-cta]");
  expect(cta?.textContent).toBe("Become a tester");
  expect(cta?.getAttribute("href")).toBe(SIGN_IN);
  expect(SIGN_IN).toBe("/login?next=%2Ftesters");
  expect(host.querySelector("form")).toBeNull();
  // Never a price.
  expect(host.textContent).not.toMatch(/₹|price|\bfree trial\b/i);
});

it("asks the server who is signed in, then offers the three fields", async () => {
  const fetcher = vi.fn(async () =>
    json({ state: "none", email: "ravi.tester@gmail.com" }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<TestersPage />));
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/sales-xray/testers/me",
    expect.objectContaining({ method: "GET", credentials: "same-origin" }),
  );
  expect(host.textContent).toContain("Joining as ravi.tester@gmail.com");
  expect(host.querySelector('input[name="phone_model"]')).not.toBeNull();
  expect(host.querySelectorAll('input[name="role"]')).toHaveLength(4);
  expect(host.querySelector('input[name="business"]')).not.toBeNull();
  const submit = host.querySelector<HTMLButtonElement>('button[type="submit"]');
  expect(submit?.disabled).toBe(true);
});

function type(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

it("joins the waitlist once and says what happens next", async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === "POST"
      ? json({
          state: "waiting",
          email: "ravi.tester@gmail.com",
          phone_model: "Redmi 13",
        })
      : json({ state: "none", email: "ravi.tester@gmail.com" }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<TestersPage initial={me("none")} />));
  await act(async () => {
    type(host.querySelector('input[name="phone_model"]')!, "Redmi 13");
    type(host.querySelector('input[name="business"]')!, "Solar panels");
    host.querySelector<HTMLInputElement>('input[value="seller"]')!.click();
  });
  await act(async () => {
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    phone_model: "Redmi 13",
    role: "seller",
    business: "Solar panels",
  });
  expect(host.textContent).toContain("You're on the list");
  expect(host.textContent).toContain("ravi.tester@gmail.com");
});

it("shows Play's two steps at once to a tester the team has added", async () => {
  await act(async () => root.render(<TestersPage initial={me("ready")} />));
  const steps = [
    ...host.querySelectorAll<HTMLAnchorElement>("a[data-step]"),
  ].map((link) => [link.dataset.step, link.getAttribute("href"), link.target]);
  expect(steps).toEqual([
    ["1", TESTERS.optInUrl, "_blank"],
    ["2", TESTERS.playUrl, "_blank"],
  ]);
  expect(TESTERS.optInUrl).toBe(
    "https://play.google.com/apps/testing/com.authorityclosers.salesxray",
  );
  expect(host.textContent).toContain("Item not found");
  expect(host.textContent).toContain("signed in as ravi.tester@gmail.com");
});

it("tells an approved, a waiting and a declined person where they stand", async () => {
  for (const [state, words] of [
    ["approved", "You're approved"],
    ["waiting", "You're on the list"],
    ["declined", "Thanks for applying"],
  ] as const) {
    await act(async () =>
      root.render(<TestersPage key={state} initial={me(state)} />),
    );
    expect(host.textContent).toContain(words);
    expect(host.querySelector("a[data-step]")).toBeNull();
  }
});

it("reads the server's answer defensively and knows an Android browser from the app", () => {
  expect(parseTesterMe({ state: "ready", email: "a@b.test" })).toMatchObject({
    state: "ready",
  });
  expect(parseTesterMe({ state: "maybe", email: "a@b.test" })).toBeNull();
  expect(parseTesterMe({ state: "ready" })).toBeNull();
  expect(
    isAndroidBrowser("Mozilla/5.0 (Linux; Android 14; K) Chrome/130 Mobile"),
  ).toBe(true);
  expect(
    isAndroidBrowser(
      "Mozilla/5.0 (Linux; Android 14; K) Chrome/130 Mobile SalesXrayApp/1.0.99",
    ),
  ).toBe(false);
  expect(isAndroidBrowser("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0)")).toBe(
    false,
  );
});
