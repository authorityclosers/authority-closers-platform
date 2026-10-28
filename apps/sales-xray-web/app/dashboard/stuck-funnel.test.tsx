// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: unknown;
    href: string;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children as never}
    </a>
  ),
}));

import type { Performance } from "../leads/leads-client";
import { StuckFunnel, stuckInsight } from "./stuck-funnel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner Home v3 (28 Oct 2026, A): the study's snapshot, 162 + 3 + 1 + 0 = 166.
const SNAPSHOT = { new: 162, follow_up: 3, not_connected: 1, interested: 0 };

const report = (pipeline: Record<string, number>): Performance =>
  ({
    days: 7,
    start: "2026-10-22",
    end: "2026-10-28",
    current: {},
    previous: {},
    sellers: [],
    pipeline,
  }) as unknown as Performance;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  // No pipelines or stage names here: the stage words fall back to the kinds.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("no server"))),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("says where most open leads wait, and what to do", () => {
  expect(stuckInsight(SNAPSHOT)).toEqual({
    kind: "new",
    count: 162,
    share: "98% of open leads are still untouched.",
    next: "Call the newest first.",
  });
  expect(stuckInsight({ follow_up: 5, new: 2 })?.next).toBe(
    "Clear the late ones first.",
  );
  // A tie goes to the earlier stage: the first call comes first.
  expect(stuckInsight({ new: 4, interested: 4 })?.kind).toBe("new");
  expect(stuckInsight({})).toBeNull();
});

it("draws every stage with its count, a true zero kept, each opening its leads", async () => {
  await act(async () =>
    root.render(<StuckFunnel performance={report(SNAPSHOT)} />),
  );
  await act(async () => Promise.resolve());
  expect(host.querySelector("h2")?.textContent).toBe("Where leads get stuck");
  expect(host.textContent).toContain("166 open leads · right now");
  expect(host.textContent).toContain("98% of open leads are still untouched.");
  const stages = Array.from(host.querySelectorAll("li[data-kind]"), (item) => [
    item.getAttribute("data-kind"),
    item.querySelector("strong")?.textContent,
    item.querySelector("a")?.getAttribute("href"),
  ]);
  expect(stages).toEqual([
    ["new", "162", "/leads?tab=all&stage=new"],
    ["not_connected", "1", "/leads?tab=all&stage=not_connected"],
    ["follow_up", "3", "/leads?tab=all&stage=follow_up"],
    ["interested", "0", "/leads?tab=all&stage=interested"],
  ]);
  expect(host.querySelectorAll("[data-zero]")).toHaveLength(1);
  expect(host.querySelector("[data-top]")?.closest("li")?.dataset.kind).toBe(
    "new",
  );
  const action = Array.from(host.querySelectorAll("a")).find((link) =>
    link.textContent?.startsWith("Open 162"),
  );
  expect(action?.getAttribute("href")).toBe("/leads?tab=all&stage=new");
});

it("says so when nothing is open", async () => {
  await act(async () => root.render(<StuckFunnel performance={report({})} />));
  expect(host.textContent).toContain("No open leads right now.");
  expect(host.textContent).toContain("0 open leads · right now");
});
