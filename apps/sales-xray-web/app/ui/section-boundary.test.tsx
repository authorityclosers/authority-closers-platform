// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { callDate } from "../call-status";
import { unnamedCallName } from "../call-label";
import { SectionBoundary } from "./section-boundary";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let broken = true;

function Fragile() {
  if (broken) throw new RangeError("Invalid time value");
  return <p>Team calls loaded</p>;
}

beforeEach(() => {
  broken = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it("leaves one quiet line with Try again, and the rest of the page stays", async () => {
  await act(async () => {
    root.render(
      <>
        <h1>Organisation</h1>
        <SectionBoundary name="Team calls">
          <Fragile />
        </SectionBoundary>
      </>,
    );
  });
  expect(host.querySelector("h1")?.textContent).toBe("Organisation");
  const line = host.querySelector("[data-section-error]");
  expect(line?.getAttribute("data-section-error")).toBe("Team calls");
  expect(line?.textContent).toContain("Team calls couldn't be shown.");
  expect(line?.textContent).toContain("The rest of this page is up to date.");
  // The dev site names the fault.
  expect(line?.textContent).toContain("RangeError: Invalid time value");

  broken = false;
  await act(async () => host.querySelector("button")?.click());
  expect(host.textContent).toContain("Team calls loaded");
  expect(host.querySelector("[data-section-error]")).toBeNull();
});

it("starts again when its reset key changes (a new page)", async () => {
  const render = (key: string) =>
    root.render(
      <SectionBoundary
        name="This screen"
        note="Your calls are safe."
        resetKey={key}
      >
        <Fragile />
      </SectionBoundary>,
    );
  await act(async () => render("/calls"));
  expect(host.textContent).toContain("Your calls are safe.");
  broken = false;
  await act(async () => render("/dashboard"));
  expect(host.textContent).toContain("Team calls loaded");
});

it("never throws on a date a server sent wrong", () => {
  expect(callDate("yesterday")).toBe("Date unknown");
  expect(unnamedCallName("")).toBe("Sales call");
  expect(unnamedCallName("2026-10-09T10:15:00Z")).toMatch(/^Sales call · /);
});
