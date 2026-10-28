// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { analyticsFixture } from "../review-fixture/analytics/fixture";
import { AnalyticsView } from "./analytics-view";
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});
it("sorts people, shows seven at first, and opens their People page", () => {
  act(() => root.render(<AnalyticsView team initial={analyticsFixture} />));
  expect(
    host.querySelectorAll('ul[aria-label="People sorted by calls"] li'),
  ).toHaveLength(7);
  const first = host.querySelector("ul a");
  expect(first?.textContent).toContain("Kiva Fictional");
  expect(first?.getAttribute("href")).toContain("/organisation/people/");
  const all = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === "Show all (8)",
  )!;
  act(() => all.click());
  expect(host.querySelectorAll("ul li")).toHaveLength(8);
  expect(host.querySelectorAll('svg[role="img"]')).toHaveLength(8);
});
it("shows a seller who only works leads when comparing notes", () => {
  act(() => root.render(<AnalyticsView team initial={analyticsFixture} />));
  const notes = [
    ...host.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Compare activity"] button',
    ),
  ].find((b) => b.textContent === "Notes")!;
  act(() => notes.click());
  const person = [...host.querySelectorAll("li")].find((row) =>
    row.textContent?.includes("Lumi Sample"),
  );
  expect(person?.textContent).toContain("30 notes");
  expect(person?.querySelector("svg")?.getAttribute("aria-label")).toContain(
    "daily activity updates",
  );
});
it("labels partial comparisons and gaps instead of suggesting inactivity", () => {
  act(() =>
    root.render(
      <AnalyticsView
        team
        initial={{ ...analyticsFixture, cursor: "2026-10-20T12:00:00Z" }}
      />,
    ),
  );
  expect(host.textContent).toContain("Comparison unavailable");
  expect(host.textContent).toContain("Partial history");
  expect(host.querySelector("svg")?.getAttribute("aria-label")).toContain(
    "unavailable",
  );
});
it("offers leads as the next action for an empty period", () => {
  act(() =>
    root.render(
      <AnalyticsView team initial={{ ...analyticsFixture, items: [] }} />,
    ),
  );
  expect(host.textContent).toContain("No activity recorded this period");
  expect(host.querySelector("ul")).toBeNull();
  expect(host.querySelector('a[href="/leads"]')?.textContent).toBe(
    "Open leads",
  );
});

it("shows message-only work in the daily line instead of an idle state", () => {
  const message = {
    ...analyticsFixture.items[0],
    event: { ...analyticsFixture.items[0].event, kind: "message" as const },
  };
  act(() =>
    root.render(
      <AnalyticsView
        team
        initial={{ ...analyticsFixture, items: [message] }}
      />,
    ),
  );
  expect(host.textContent).not.toContain("No activity recorded");
  expect(host.textContent).toContain("Other updates: 1");
  expect(host.querySelector("ul a")?.textContent).toContain("Mira Fictional");
  expect(host.querySelector("svg")?.getAttribute("aria-label")).toContain(
    "daily activity updates",
  );
});
