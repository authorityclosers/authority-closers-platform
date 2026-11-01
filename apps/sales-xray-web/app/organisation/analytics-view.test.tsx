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

/** The server's summary for the fixture, as the endpoint sends it. */
function summaryBody() {
  const data = activitySummary(analyticsFixture);
  const iso = (day: number) =>
    new Date(day * 86400000).toISOString().slice(0, 10);
  return {
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
}

// Competitor teardown 15 (1 Nov 2026): Today, 7 days or 30 days, kept in
// the address; every number opens the list behind it; owners export.
it("reads the period picked, and keeps it in the address", async () => {
  const thirty = summaryBody();
  const week = {
    ...thirty,
    days: 7,
    start: thirty.today,
    prior: thirty.today,
    people: thirty.people.map((p) => ({ ...p, daily: [] })),
  };
  const fetch = vi.fn((input: string) =>
    Promise.resolve(
      new Response(JSON.stringify(input.includes("days=7") ? week : thirty)),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<AnalyticsView team />));
  expect(fetch.mock.calls[0][0]).toContain("days=30");
  const seven = [
    ...host.querySelectorAll<HTMLButtonElement>('[aria-label="Period"] button'),
  ].find((b) => b.textContent === "7 days")!;
  await act(async () => seven.click());
  expect(fetch.mock.calls.at(-1)![0]).toContain("days=7");
  expect(new URL(window.location.href).searchParams.get("days")).toBe("7");
  // One day draws no daily lines; the bars say it.
  expect(
    host.querySelector('ul[aria-label="People sorted by calls"] svg'),
  ).toBeNull();
  window.history.replaceState(null, "", "/");
});

it("opens the calls behind the Calls number, each opening its lead", async () => {
  const body = summaryBody();
  const at = new Date(
    Date.parse(analyticsFixture.now) - 3600_000,
  ).toISOString();
  const event = (kind: string, extra: object) => ({
    kind,
    at,
    actor_name: "kiva fictional",
    connected: null,
    duration_seconds: null,
    note: null,
    stage_label: null,
    ...extra,
  });
  const feed = {
    items: [
      {
        event_id: "e1",
        lead_id: "lead-1",
        lead_name: "asha fictional",
        stage_label: null,
        event: event("call", { connected: true, duration_seconds: 125 }),
      },
      {
        event_id: "e2",
        lead_id: "lead-2",
        lead_name: "ravi sample",
        stage_label: null,
        event: event("note", { note: "Wants EMI options" }),
      },
      {
        event_id: "e3",
        lead_id: "lead-3",
        lead_name: "meera sample",
        stage_label: null,
        event: event("call", { connected: false }),
      },
    ],
    next_before: null,
    counts: {},
  };
  const fetch = vi.fn((input: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(input.includes("/activity/summary") ? body : feed),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<AnalyticsView team />));
  const calls = host.querySelector<HTMLButtonElement>(
    'button[aria-label^="Calls, "]',
  )!;
  await act(async () => calls.click());
  expect(fetch.mock.calls.at(-1)![0]).toContain(
    "/v1/lead-desk/activity?day=recent&team=true",
  );
  const rows = [...document.querySelectorAll<HTMLAnchorElement>("dialog li a")];
  expect(rows.map((row) => row.getAttribute("href"))).toEqual([
    "/leads#lead=lead-1",
    "/leads#lead=lead-3",
  ]);
  expect(rows[0].textContent).toContain("Asha Fictional");
  expect(rows[0].textContent).toContain("Kiva Fictional · Connected · 2 min");
  expect(rows[1].textContent).toContain("Not connected");
});

it("exports the period's numbers per person for owners", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(summaryBody())))),
  );
  const made: Blob[] = [];
  const create = vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    made.push(blob as Blob);
    return "blob:fictional";
  });
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  await act(async () => root.render(<AnalyticsView team />));
  const exportButton = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Export the period as a CSV file"]',
  )!;
  act(() => exportButton.click());
  expect(click).toHaveBeenCalledTimes(1);
  const text = await made[0].text();
  expect(text.split("\n")[0]).toBe(
    'Person,Calls,Conversations,Notes,Stage moves,All updates,"Calls, period before","Conversations, period before","Notes, period before","Stage moves, period before"',
  );
  expect(text).toContain('"Calls, period before"');
  expect(text).toContain("Kiva Fictional,");
  create.mockRestore();
  revoke.mockRestore();
  click.mockRestore();
});

it("shows no export to someone who sees only their own work", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(summaryBody())))),
  );
  await act(async () => root.render(<AnalyticsView team={false} />));
  expect(host.textContent).not.toContain("Export");
});
