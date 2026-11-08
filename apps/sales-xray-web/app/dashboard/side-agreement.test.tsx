import { act, type AnchorHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import type { Effort, SideEffort } from "../performance/performance-client";
import type { HomeSide } from "./my-day-client";
import { onSide, TodayPerformance } from "./seller-home";
import { elsewhere } from "./team-floor";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner and Swamini, 4 Nov 2026 (#170 #174 #175): every call that day was on
// Cold leads, so Inbound said 0 tried beside Recent calls and "11 connected
// calls without a recording" that were all Cold. Fictional numbers throughout.

let root: Root | null = null;
let host: HTMLDivElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

const side = (attempted: number): SideEffort =>
  ({ attempted, connected: 0, talk_seconds: 0 }) as SideEffort;

it("lists only the side shown's recent calls; a call with no side is Inbound", () => {
  const calls = [
    { id: "a", side: "cold" as const },
    { id: "b", side: "inbound" as const },
    { id: "c", side: null },
    { id: "d" },
  ];
  expect(onSide(calls, "inbound").map((call) => call.id)).toEqual([
    "b",
    "c",
    "d",
  ]);
  expect(onSide(calls, "cold").map((call) => call.id)).toEqual(["a"]);
  expect(onSide(calls, null)).toHaveLength(4);
});

it("says where today's calls are when the side shown has none", () => {
  const effort = { inbound: side(0), cold: side(35) } as Effort;
  expect(elsewhere("inbound", effort)).toBe(" · 35 tried on Cold");
  expect(elsewhere("cold", effort)).toBe("");
  expect(
    elsewhere("inbound", { inbound: side(2), cold: side(35) } as Effort),
  ).toBe("");
  expect(elsewhere("inbound", null)).toBe("");
});

it("a seller's Inbound performance at 0 says how many were tried on Cold", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const numbers = (calls: number) =>
    ({
      numbers: {
        calls,
        connected: 0,
        not_connected: calls,
        unknown: 0,
        talk_seconds: 0,
        follow_ups_done: 0,
      },
    }) as unknown as HomeSide;
  await act(async () =>
    root?.render(
      <TodayPerformance side="inbound" own={numbers(0)} other={numbers(3)} />,
    ),
  );
  expect(host.textContent).toContain("3 tried on Cold today");
  await act(async () =>
    root?.render(
      <TodayPerformance side="inbound" own={numbers(1)} other={numbers(3)} />,
    ),
  );
  expect(host.textContent).not.toContain("tried on Cold");
});
