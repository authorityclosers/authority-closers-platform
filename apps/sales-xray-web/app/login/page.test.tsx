// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { learnerAuthLinksForHost } from "../account-auth";
import LoginPage from "./page";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const config = {
  enabled: true,
  consent_version: "terms-v1",
  google_enabled: true,
  expires_in_seconds: 600,
  resend_after_seconds: 60,
};
const session = {
  person_id: "eaed7960-d4d0-4675-bd34-5b6a7d9c598d",
  session_id: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
  selected_tenant_id: null,
  workspaces: [],
};
let host: HTMLDivElement;
let root: Root;
let assign: ReturnType<typeof vi.spyOn>;

async function flush() {
  await act(async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); });
}

async function mount() {
  await act(async () => root.render(<LoginPage />));
  await flush();
}

async function click(text: string) {
  const button = Array.from(host.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`Missing ${text}`);
  await act(async () => button.click());
  await flush();
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  assign = vi.spyOn(window.location, "assign").mockImplementation(() => {});
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("opens the versioned code-first flow without initiating sign-in before consent", async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url !== "/v1/auth/email-code/config?surface=sales_xray") throw new Error(`Unexpected ${url}`);
    return Response.json(config);
  });
  vi.stubGlobal("fetch", fetcher);
  await mount();

  expect(host.textContent).toContain("Your next better");
  expect(host.querySelector('a[aria-label="Sales Xray home"]')?.getAttribute("href")).toBe("/");
  expect(host.querySelector<HTMLInputElement>("#account-email")).not.toBeNull();
  expect(host.querySelector<HTMLButtonElement>("button[type=submit]")?.disabled).toBe(true);
  expect(Array.from(host.querySelectorAll("button")).find((item) => item.textContent?.includes("Continue with Google"))?.disabled).toBe(true);
  expect(fetcher.mock.calls.map((call) => call[0])).toEqual(["/v1/auth/email-code/config?surface=sales_xray"]);
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  expect(host.querySelector<HTMLButtonElement>("button[type=submit]")?.disabled).toBe(false);
  expect(Array.from(host.querySelectorAll("button")).find((item) => item.textContent?.includes("Continue with Google"))?.disabled).toBe(false);
  expect(assign).not.toHaveBeenCalled();
});

it("retains password access during code config failure and redirects only after canonical session confirmation", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.includes("/config")) return new Response(null, { status: 503 });
    if (url === "/v1/auth/password/login") return Response.json({ authenticated: true });
    if (url === "/v1/me/workspaces") return Response.json(session);
    throw new Error(`Unexpected ${url}`);
  }));
  await mount();
  expect(host.textContent).toContain("Email code sign-in isn’t available right now.");
  expect(host.textContent).not.toContain("Sign-in is temporarily unavailable.");
  expect(host.querySelector("#account-email")).toBeNull();
  expect(host.querySelectorAll('button[disabled]')).toHaveLength(0);
  await click("Use my existing password");
  const email = host.querySelector<HTMLInputElement>("#account-password-email")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(email, "existing@example.test");
    email.dispatchEvent(new Event("input", { bubbles: true }));
    email.dispatchEvent(new Event("change", { bubbles: true }));
  });
  host.querySelector<HTMLInputElement>("#account-password")!.value = "synthetic-password";
  await act(async () => host.querySelector<HTMLFormElement>("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await flush();
  expect(calls).toEqual([
    "/v1/auth/email-code/config?surface=sales_xray",
    "/v1/auth/password/login",
    "/v1/me/workspaces",
  ]);
  expect(assign).toHaveBeenCalledWith("/");
  expect(host.querySelector<HTMLInputElement>("#account-password")).toBeNull();
});

it("offers password access when code sign-in is disabled and restores code after a successful recheck", async () => {
  let configReads = 0;
  const fetcher = vi.fn(async (url: string) => {
    if (url !== "/v1/auth/email-code/config?surface=sales_xray") throw new Error(`Unexpected ${url}`);
    configReads += 1;
    return Response.json(configReads === 1
      ? { ...config, enabled: false, consent_version: null, google_enabled: false }
      : config);
  });
  vi.stubGlobal("fetch", fetcher);
  await mount();
  expect(host.textContent).toContain("Email code sign-in isn’t available right now.");
  expect(host.querySelector("#account-email")).toBeNull();
  await click("Check code sign-in again");
  expect(host.querySelector("#account-email")).not.toBeNull();
  expect(host.textContent).not.toContain("Email code sign-in isn’t available right now.");
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(assign).not.toHaveBeenCalled();
});

it("does not blame credentials when the password endpoint cannot complete sign-in", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.includes("/config")) return new Response(null, { status: 404 });
    if (url === "/v1/auth/password/login") return new Response(null, { status: 404 });
    throw new Error(`Unexpected ${url}`);
  }));
  await mount();
  await click("Use my existing password");
  const email = host.querySelector<HTMLInputElement>("#account-password-email")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(email, "existing@example.test");
    email.dispatchEvent(new Event("input", { bubbles: true }));
    email.dispatchEvent(new Event("change", { bubbles: true }));
  });
  host.querySelector<HTMLInputElement>("#account-password")!.value = "synthetic-password";
  await act(async () => host.querySelector<HTMLFormElement>("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await flush();
  expect(host.textContent).toContain("We couldn’t complete password sign-in.");
  expect(calls).toEqual([
    "/v1/auth/email-code/config?surface=sales_xray",
    "/v1/auth/password/login",
  ]);
  expect(assign).not.toHaveBeenCalled();
});

it("keeps learner recovery URLs limited to source-owned hosts", () => {
  expect(learnerAuthLinksForHost("salesxray-staging.authorityclosers.com")).toEqual({
    registerHref: "https://learner-staging.authorityclosers.com/register",
    forgotPasswordHref: "https://learner-staging.authorityclosers.com/forgot-password",
  });
  expect(learnerAuthLinksForHost("salesxray.authorityclosers.com")).toEqual({
    registerHref: "https://learner.authorityclosers.com/register",
    forgotPasswordHref: "https://learner.authorityclosers.com/forgot-password",
  });
  expect(learnerAuthLinksForHost("localhost")).toEqual({ registerHref: null, forgotPasswordHref: null });
  expect(learnerAuthLinksForHost("untrusted.example")).toEqual({ registerHref: null, forgotPasswordHref: null });
});
