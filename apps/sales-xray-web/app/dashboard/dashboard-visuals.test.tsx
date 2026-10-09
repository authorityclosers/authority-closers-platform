// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { axisTicks, DayBars, StatusSplit } from "./dashboard-visuals";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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

it("draws a zero-based axis with at most four round steps", () => {
  expect(axisTicks(0)).toEqual([0, 1]);
  expect(axisTicks(3)).toEqual([0, 1, 2, 3]);
  expect(axisTicks(7)).toEqual([0, 2, 4, 6, 8]);
  expect(axisTicks(13)).toEqual([0, 5, 10, 15]);
  expect(axisTicks(37)).toEqual([0, 10, 20, 30, 40]);
});

it("labels every day and scales bars against the axis top, not the busiest day", async () => {
  const days = Array.from({ length: 30 }, (_, index) => ({
    date: `2026-09-${String(index + 1).padStart(2, "0")}`,
    analysed: index === 29 ? 3 : index === 10 ? 1 : 0,
    analysedSeconds: index === 29 ? 1800 : index === 10 ? 600 : 0,
  }));
  await act(async () => root.render(<DayBars days={days} />));
  const bars = [...host.querySelectorAll<HTMLButtonElement>("button")];
  expect(bars).toHaveLength(30);
  expect(bars[29].getAttribute("aria-label")).toBe("Today: 3 calls, 30 min");
  expect(bars[10].querySelector("i")?.style.height).toBe(`${(1 / 3) * 100}%`);
  expect(bars[0].querySelector("i")?.hasAttribute("data-zero")).toBe(true);
  expect(host.textContent).toContain("4 calls");
  await act(async () => {
    bars[10].dispatchEvent(new FocusEvent("focus"));
    bars[10].focus();
  });
  expect(host.querySelector("figcaption")?.textContent).toContain(
    "1 call · 10 min",
  );
});

it("lists every status in full with its count, including zeros", async () => {
  await act(async () =>
    root.render(
      <StatusSplit
        summary={{ total: 10, processing: 2, completed: 7, needsAttention: 1 }}
      />,
    ),
  );
  const rows = [...host.querySelectorAll("li")].map((row) => row.textContent);
  expect(rows).toEqual([
    "Report ready770%",
    "In progress220%",
    "Needs attention110%",
    "Other00%",
  ]);
  expect(host.textContent).toContain("10 saved calls");
});
