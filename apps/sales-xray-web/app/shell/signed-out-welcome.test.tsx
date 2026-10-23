import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const access = vi.hoisted(() => ({ value: null as unknown }));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => access.value,
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/leads" }));

const { SignedOutWelcome, signInHref } = await import("./signed-out-welcome");

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  access.value = { authenticated: false };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("signs in and comes back to the page the person was on", async () => {
  await act(async () =>
    root.render(
      <SignedOutWelcome title="Sign in to see your leads" text="Your leads." />,
    ),
  );
  const signIn = [...host.querySelectorAll("a")].find((a) =>
    a.textContent?.includes("Sign in"),
  );
  expect(signIn?.getAttribute("href")).toBe("/login?next=%2Fleads");
  expect(host.querySelector("h2")?.textContent).toBe(
    "Sign in to see your leads",
  );
  // No guest path unless the page offers one, and never a price.
  expect(host.textContent).not.toContain("without an account");
  expect(host.textContent).not.toMatch(/₹|price|cost/i);
});

it("uses the app's own sign-in when it has one", async () => {
  const requestAccountSignIn = vi.fn();
  access.value = { authenticated: false, requestAccountSignIn };
  await act(async () =>
    root.render(
      <SignedOutWelcome title="T" text="t" guestHref="/analysis/new" />,
    ),
  );
  const links = [...host.querySelectorAll("a")];
  await act(async () => links[0].click());
  expect(requestAccountSignIn).toHaveBeenCalledOnce();
  expect(links[1].getAttribute("href")).toBe("/analysis/new");
});

it("fits above the phone tab bar: compact rows, a 44 px guest link, no wave on short screens", () => {
  // Redmi test, 23 Oct: the guest link and account line sat under the bar.
  const css = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "signed-out-welcome.module.css",
    ),
    "utf8",
  );
  const phone = css.slice(css.indexOf("@media (max-width: 899.98px) {"));
  expect(phone).toMatch(/\.points li \{[^}]*font-size: var\(--sx-text-sm\)/);
  expect(phone).toMatch(/\.guest \{[^}]*min-height: 44px/);
  expect(css).toMatch(
    /@media \(max-width: 899\.98px\) and \(max-height: 760px\) \{\s*\.wave \{\s*display: none;/,
  );
});

it("never sends sign-in back to sign-in or off the site", () => {
  expect(signInHref("/login")).toBe("/login");
  expect(signInHref(null)).toBe("/login");
  expect(signInHref("/analysis/calls/1?view=coaching")).toBe(
    "/login?next=%2Fanalysis%2Fcalls%2F1%3Fview%3Dcoaching",
  );
});
