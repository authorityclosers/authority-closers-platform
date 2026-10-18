// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";

import type { ConsoleAccess } from "../lib/nav";
import type { Workspace } from "../lib/workspaces";
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

async function render(
  access: ConsoleAccess = dipak,
  workspaces: Workspace[] | null = null,
) {
  await act(async () =>
    root.render(
      <ConsoleShell
        access={access}
        environment="staging"
        workspaces={workspaces}
      >
        <p>Page body</p>
      </ConsoleShell>,
    ),
  );
}

const WORKSPACES: Workspace[] = [
  {
    id: "c0000000-0000-4000-8000-000000000001",
    name: "Fictional Closers",
    registeredName: "Fictional Closers",
    kind: "company",
    status: "active",
    members: 5,
    calls: 37,
  },
  {
    id: "c0000000-0000-4000-8000-000000000002",
    name: "Personal accounts",
    registeredName: "Fictional Public Learners",
    kind: "personal",
    status: "active",
    members: 10,
    calls: 136,
  },
  {
    id: "c0000000-0000-4000-8000-000000000003",
    name: "AC Operations",
    registeredName: "Fictional Closers",
    kind: "operations",
    status: "active",
    members: 2,
    calls: 0,
  },
];
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

it("names every icon-only control, including Go to on phones", async () => {
  await render();
  const unnamed = [...host.querySelectorAll("button")].filter(
    (button) =>
      !button.getAttribute("aria-label") && !button.textContent?.trim(),
  );
  expect(unnamed).toEqual([]);
  expect(
    host
      .querySelector('button[aria-keyshortcuts="Control+K Meta+K"]')
      ?.getAttribute("aria-label"),
  ).toBe("Go to a section or call");
});

it("heads the rail with the signed-in person and lists every workspace by kind", async () => {
  await render(dipak, WORKSPACES);
  const person = host.querySelector<HTMLButtonElement>(
    'button[aria-label^="Signed in as Dipak Example"]',
  )!;
  expect(person.textContent).toContain("Admin · AC Operations");
  const panel = host.querySelector<HTMLElement>(
    `#${CSS.escape(person.getAttribute("aria-controls")!)}`,
  )!;
  expect(panel.hidden).toBe(true);
  await act(async () => person.click());
  expect(panel.hidden).toBe(false);
  expect(panel.textContent).toContain("dipak@authorityclosers.com");
  const groups = [...panel.querySelectorAll("section")].map((section) =>
    section.getAttribute("aria-label"),
  );
  expect(groups).toEqual([
    "Our company",
    "Personal accounts",
    "Staff workspace",
  ]);
  // Each one says what it is, and the registry name is kept in view.
  expect(panel.textContent).toContain("Our company5 people · 37 calls");
  expect(panel.textContent).toContain(
    "Registered as “Fictional Public Learners”",
  );
  expect(
    panel.querySelector(
      'a[href="/calls?organisation=c0000000-0000-4000-8000-000000000002"]',
    ),
  ).not.toBeNull();
  // The staff workspace holds no calls, so it opens nothing.
  expect(
    panel.querySelector(
      'a[href="/calls?organisation=c0000000-0000-4000-8000-000000000003"]',
    ),
  ).toBeNull();
  expect(panel.textContent).toContain("2 people · no calls");
  await act(async () =>
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(panel.hidden).toBe(true);
  expect(document.activeElement).toBe(person);
});

it("shows only the person, with no workspace list, without platform read", async () => {
  await render({ ...dipak, platform: [] }, null);
  expect(host.textContent).toContain("Dipak Example");
  expect(host.textContent).not.toContain("Organisations and accounts");
  expect(host.textContent).not.toContain("Authority Closers");
});
