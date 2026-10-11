// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";

import type { ConsoleAccess } from "../lib/nav";
import { ConsoleShell } from "./shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/calls",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const dipak: ConsoleAccess = {
  state: "verified",
  email: "dipak@authorityclosers.com",
  displayName: "Dipak Example",
  role: "admin",
  permissions: ["admin_surface", "learner_diagnose"],
  platform: ["platform_tenants_read"],
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  localStorage.clear();
  vi.spyOn(api, "loadAdminSession").mockReturnValue(new Promise(() => {}));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  localStorage.clear();
});

async function render(access: ConsoleAccess = dipak) {
  await act(async () =>
    root.render(
      <ConsoleShell access={access} environment="staging">
        <p>Page body</p>
      </ConsoleShell>,
    ),
  );
}
function button(label: string) {
  const node = host.querySelector<HTMLButtonElement>(
    `button[aria-label="${label}"]`,
  );
  expect(node).not.toBeNull();
  return node!;
}

it("lists only the sections the account can use and marks the current one", async () => {
  await render();
  const links = [...host.querySelectorAll('nav[aria-label="Sections"] a')].map(
    (a) => a.getAttribute("href"),
  );
  expect(links).toContain("/calls");
  expect(links).toContain("/people");
  expect(links).toContain("/platform/organisations");
  expect(links).not.toContain("/platform?tab=billing");
  expect(links).not.toContain("/learning-operations");
  expect(
    host.querySelector('a[href="/calls"][aria-current="page"]'),
  ).not.toBeNull();
  expect(host.textContent).toContain("Page body");
  expect(host.textContent).toContain("staging");
});

it("hides Sales Xray review from accounts outside the control list", async () => {
  await render({ ...dipak, email: "someone@example.com" });
  expect(host.querySelector('a[href="/calls"]')).toBeNull();
  expect(host.querySelector('a[href="/people"]')).not.toBeNull();
});

it("persists navigation collapse across a fresh shell mount", async () => {
  await render();
  await act(async () => button("Collapse navigation").click());
  expect(host.querySelector("[data-collapsed]")).not.toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);
  await render();
  expect(button("Expand navigation").getAttribute("aria-expanded")).toBe(
    "false",
  );
});

it("opens the phone sheet, makes the page inert, and restores it on Escape", async () => {
  await render();
  await act(async () => button("Open navigation").click());
  expect(host.querySelector("main")?.closest("[inert]")).not.toBeNull();
  await act(async () =>
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(host.querySelector("main")?.closest("[inert]")).toBeNull();
  expect(document.activeElement).toBe(button("Open navigation"));
});

it("asks the active editor before signing out and explains a failed sign-out", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("", { status: 503 }));
  let proceed: (() => void) | undefined;
  const guard = (event: Event) => {
    event.preventDefault();
    proceed = (event as CustomEvent<{ proceed: () => void }>).detail.proceed;
  };
  document.addEventListener("ac:studio-before-leave", guard);
  try {
    await render();
    await act(async () => button("Sign out").click());
    expect(fetcher).not.toHaveBeenCalled();
    await act(async () => proceed!());
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/auth/logout",
      expect.objectContaining({ method: "POST" }),
    );
    expect(host.textContent).toContain("Sign-out could not be confirmed");
  } finally {
    document.removeEventListener("ac:studio-before-leave", guard);
  }
});

it("draws the frame at once, before the client session check finishes", async () => {
  await render();
  expect(button("Collapse navigation")).not.toBeNull();
  expect(host.textContent).toContain("Dipak Example");
  expect(host.querySelectorAll("main")).toHaveLength(1);
});
