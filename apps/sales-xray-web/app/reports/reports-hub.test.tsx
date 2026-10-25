// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import { ReportsHub, standouts, type ReportsData } from "./reports-hub";
import { REPORTS_FIXTURE } from "./reports-fixture";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  window.history.replaceState(null, "", "/reports");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const render = (manager: boolean, data: ReportsData) =>
  act(async () => root.render(<ReportsHub manager={manager} data={data} />));

const titles = () =>
  Array.from(host.querySelectorAll("strong"), (item) => item.textContent);

// Owner, 25 Oct 2026: intelligence from real numbers, most urgent first.
it("says what stands out, most urgent first, at most three", () => {
  expect(standouts(REPORTS_FIXTURE).map((fact) => fact.text)).toEqual([
    "3 calls need a look",
    "12 leads are overdue for a call",
    "2 new leads waited past 10 min for a first call",
  ]);
  expect(
    standouts({ ...REPORTS_FIXTURE, calls: null, sla: null }).map(
      (fact) => fact.key,
    ),
  ).toEqual(["overdue", "connect", "lost"]);
  expect(standouts({ calls: null, pipeline: null })).toEqual([]);
});

it("puts every kind of report in one place, by category", async () => {
  await render(true, REPORTS_FIXTURE);
  expect(
    Array.from(host.querySelectorAll("h2"), (item) => item.textContent),
  ).toEqual(["What stands out", "Calls", "Leads", "Team"]);
  expect(titles()).toEqual([
    "Call reports",
    "Coaching",
    "Pipeline numbers",
    "Lost and junk",
    "How sales are going",
    "First response",
    "Team insights",
    "Sellers",
  ]);
  expect(host.textContent).toContain("19 reports ready · 3 need a look");
  expect(host.textContent).toContain(
    "6 won · 9 interested · 46% connected in 7 days",
  );
  expect(host.querySelector('a[href="/leads?tab=numbers"]')).not.toBeNull();
});

it("keeps the team's reports for owners and admins", async () => {
  await render(false, { calls: REPORTS_FIXTURE.calls, pipeline: null });
  expect(
    Array.from(host.querySelectorAll('[role="tab"]'), (tab) => tab.textContent),
  ).toEqual(["All", "Calls", "Leads"]);
  expect(titles()).not.toContain("How sales are going");
});

it("shows one category from its chip, kept in the address", async () => {
  await render(true, REPORTS_FIXTURE);
  const calls = Array.from(host.querySelectorAll('[role="tab"]')).find(
    (tab) => tab.textContent === "Calls",
  ) as HTMLButtonElement;
  await act(async () => calls.click());
  expect(window.location.search).toBe("?kind=calls");
  expect(titles()).toEqual(["Call reports", "Coaching"]);
  expect(host.textContent).not.toContain("What stands out");
});

it("draws each line's place while its numbers load", async () => {
  await render(true, {});
  expect(host.textContent).toContain("Call reports");
  expect(host.textContent).not.toContain("ready");
  expect(host.textContent).not.toContain("Nothing needs you");
});
