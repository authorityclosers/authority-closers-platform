// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { analyticsFixture } from "../review-fixture/analytics/fixture";
import { activitySummary } from "./analytics-data";
import { notify } from "../notice-center";
import { AnalyticsView } from "./analytics-view";
vi.mock("../notice-center", () => ({ notify: vi.fn() }));
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
  vi.unstubAllGlobals();
  vi.clearAllMocks();
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
// A teammate's People page is for those who see the team (roles.ts
// "team.view"): without it, only your own row opens your page.
it("opens only your own People page when you don't see the team", () => {
  const own = analyticsFixture.members[3].personId!;
  act(() =>
    root.render(
      <AnalyticsView team={false} personId={own} initial={analyticsFixture} />,
    ),
  );
  expect(
    host.querySelectorAll('ul[aria-label="People sorted by calls"] li'),
  ).toHaveLength(7);
  expect(
    [...host.querySelectorAll<HTMLAnchorElement>("ul a")].map((link) =>
      link.getAttribute("href"),
    ),
  ).toEqual([`/organisation/people/${encodeURIComponent(own)}`]);
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
  expect(host.textContent).toContain("Some older days haven't loaded yet");
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

it("keeps a skeleton while the single summary request loads", async () => {
  const fetch = vi.fn(() => new Promise<Response>(() => {}));
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<AnalyticsView team />));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(
    host
      .querySelector('[aria-label="Loading activity"]')
      ?.getAttribute("aria-busy"),
  ).toBe("true");
  expect(host.textContent).not.toContain("No activity recorded");
});
it("offers a corner-card retry after failure, then renders the complete summary", async () => {
  const data = activitySummary(analyticsFixture);
  const iso = (day: number) =>
    new Date(day * 86400000).toISOString().slice(0, 10);
  const body = {
    ...data,
    schema: "lead-desk/1",
    days: 30,
    now: analyticsFixture.now,
    start: iso(data.start),
    prior: iso(data.prior),
    today: iso(data.today),
    current: { ...data.current, work: data.currentWork },
    previous: { ...data.previous, work: 0 },
    people: data.people.map((p) => ({
      ...p,
      current: { ...p.current, work: p.work },
      previous: { ...p.previous, work: 0 },
      daily: p.daily.map((d, i) => ({ ...d, day: iso(data.start + i) })),
    })),
  };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response("{}", { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(body)));
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<AnalyticsView team />));
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({
      title: "Activity didn't load",
      tone: "error",
      action: expect.objectContaining({ label: "Try again" }),
    }),
  );
  expect(
    host
      .querySelector('[aria-label="Loading activity"]')
      ?.getAttribute("aria-busy"),
  ).toBe("false");
  const retry = vi.mocked(notify).mock.calls[0][0].action!;
  await act(async () => retry.run());
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(host.querySelector('[aria-label="Loading activity"]')).toBeNull();
  expect(host.textContent).toContain("Kiva Fictional");
  expect(host.textContent).not.toContain("Some older days haven't loaded yet");
  expect(host.textContent).not.toContain("Load older activity");
});
