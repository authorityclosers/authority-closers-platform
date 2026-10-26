import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch,
    ...rest
  }: {
    href: string;
    children: ReactNode;
    prefetch?: boolean;
  }) => (
    <a href={href} data-prefetch={String(prefetch)} {...rest}>
      {children}
    </a>
  ),
}));

import { CREATE_ORGANISATION_EVENT } from "../shell/shell-store";
import { FirstRun } from "./first-run";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, #20 (26 Oct 2026): one welcome line, three one-tap steps, no paragraphs.
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

const steps = () =>
  [...host.querySelectorAll("li")].map((item) => ({
    title: item.querySelector("strong")?.textContent,
    href: item.querySelector("a")?.getAttribute("href") ?? null,
  }));

it("gives a manager three steps: leads, the team, the first call", async () => {
  await act(async () => root.render(<FirstRun team="invite" />));
  expect(host.querySelector("h2")?.textContent).toBe(
    "Welcome to Sales X-Ray. Start here.",
  );
  expect(steps()).toEqual([
    { title: "Add your leads", href: "/leads?import=file" },
    { title: "Add your team", href: "/organisation?tab=team" },
    { title: "Make your first call", href: "/leads" },
  ]);
  expect(host.querySelectorAll("p")).toHaveLength(0);
});

it("opens Create an organisation from your own workspace", async () => {
  const created = vi.fn();
  window.addEventListener(CREATE_ORGANISATION_EVENT, created);
  try {
    await act(async () => root.render(<FirstRun team="create" />));
    const button = host.querySelector("button")!;
    expect(button.textContent).toContain("Add your team");
    await act(async () => button.click());
    expect(created).toHaveBeenCalledTimes(1);
  } finally {
    window.removeEventListener(CREATE_ORGANISATION_EVENT, created);
  }
});

it("gives a seller a call to analyse instead of a team step", async () => {
  await act(async () => root.render(<FirstRun team={null} />));
  expect(steps().map((step) => step.title)).toEqual([
    "Add your leads",
    "Analyse a call",
    "Make your first call",
  ]);
});

// v0.96 release check (26 Oct 2026): Home's links prefetch nothing on their
// own, so moving away at once never cuts off loads they started.
it("prefetches nothing from the first-run steps", async () => {
  await act(async () => root.render(<FirstRun team="invite" />));
  const links = [...host.querySelectorAll("a")];
  expect(links.length).toBeGreaterThan(0);
  expect(links.map((link) => link.dataset.prefetch)).toEqual(
    links.map(() => "false"),
  );
});
