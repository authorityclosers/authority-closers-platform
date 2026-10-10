// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TeamPatternsSection } from "./team-patterns-section";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const call = (n: number, hasReport = true) => ({
  id: id(n),
  ownerName: n % 2 ? "Asha Menon" : "Rahul Verma",
  label: n === 1 ? "Discovery · Amit, Pixel Digital" : null,
  createdAt: `2026-10-0${n}T10:00:00Z`,
  hasReport,
});
const report = (kind: string, discovery: string, fix: string) => ({
  report: {
    content: {
      dimensions: [
        {
          dimension_id: "discovery_deep_understanding",
          label: "Discovery & Deep Understanding",
          status: discovery,
        },
      ],
      overview: { outcome: { kind }, final_assessment: { fix_first: fix } },
    },
  },
});

let root: Root;
let host: HTMLDivElement;
let replies: Record<string, () => Response>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  replies = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method && init.method !== "GET") throw new Error("no writes");
      const match = /submissions\/([0-9a-f-]+)\/report$/.exec(url);
      const reply = match ? replies[match[1]] : undefined;
      return reply ? reply() : json({ detail: "Not Found" }, 404);
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function render(calls: ReturnType<typeof call>[]) {
  await act(async () => {
    root.render(<TeamPatternsSection calls={calls} />);
  });
  for (let i = 0; i < 5; i += 1)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
}

it("counts how calls ended, skills found only partly and each first fix", async () => {
  replies[id(1)] = () =>
    json(report("follow_up", "partial", "Ask what the budget is."));
  replies[id(2)] = () =>
    json(report("follow_up", "insufficient_evidence", "Confirm who decides."));
  replies[id(3)] = () => json(report("no_sale", "observed", "Slow down."));
  await render([call(1), call(2), call(3), call(4, false)]);

  const text = host.textContent ?? "";
  expect(text).toContain("From 3 reports in the last 30 days");
  const outcomes = [...host.querySelectorAll("h3 + ul li")][0];
  expect(outcomes.textContent).toBe("Next step agreed2");
  expect(text).toContain("Discovery & Deep Understanding2 of 3");
  // Newest first, with who and which call; links open the call read-only.
  const fixes = [...host.querySelectorAll("a")];
  expect(fixes.map((link) => link.querySelector("span")?.textContent)).toEqual([
    "Slow down.",
    "Confirm who decides.",
    "Ask what the budget is.",
  ]);
  expect(fixes[2].textContent).toContain("Asha Menon");
  expect(fixes[2].textContent).toContain("Discovery · Amit, Pixel Digital");
  expect(text).toContain("drafts, not scores");
  // A call without a report is never read.
  expect(
    vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes(id(4))),
  ).toBe(false);
});

it("shows the skeleton until every report has answered", async () => {
  let release = () => {};
  replies[id(1)] = () => json(report("closed", "observed", "Keep going."));
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        release = () => resolve(json(report("closed", "observed", "x")));
      }),
  );
  await render([call(1)]);
  expect(host.querySelector('[aria-label="Loading reports"]')).not.toBeNull();
  await act(async () => release());
  expect(host.querySelector('[aria-label="Loading reports"]')).toBeNull();
  expect(host.textContent).toContain("Deal closed");
});

it("says how many reports failed, with Try again, and keeps the rest", async () => {
  let fail = true;
  replies[id(1)] = () => json(report("closed", "observed", "Keep going."));
  replies[id(2)] = () =>
    fail
      ? json({ detail: "x" }, 500)
      : json(report("future_date", "partial", "Book the next call."));
  await render([call(1), call(2)]);
  expect(host.textContent).toContain("1 report could not be read.");
  expect(host.textContent).toContain("From 1 report");

  fail = false;
  const retry = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Try again",
  )!;
  await act(async () => retry.click());
  for (let i = 0; i < 5; i += 1)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  expect(host.textContent).toContain("From 2 reports");
  expect(host.textContent).not.toContain("could not be read");
  expect(host.textContent).toContain("Call back later");
});

it("is honest when reports can't be opened or none are ready", async () => {
  replies[id(1)] = () => json({ detail: "Forbidden" }, 403);
  await render([call(1)]);
  expect(host.textContent).toContain(
    "Teammates' reports can't be opened from here yet",
  );
  expect(host.textContent).not.toContain("Try again");

  await render([call(2, false)]);
  expect(host.textContent).toContain("shows here once reports are ready");
  expect(host.querySelector("section")).toBeNull();
});
