import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { ProcessingVisual } from "./processing-visual";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("shows a decorative phase-aware icon without duplicating the live status or inventing progress", async () => {
  await act(async () =>
    root.render(<ProcessingVisual phase="C4" paused={false} />),
  );
  expect(
    container.querySelector(
      '[data-phase="C4"][data-paused="false"][aria-hidden="true"]',
    ),
  ).not.toBeNull();
  expect(container.textContent).toBe("");
  await act(async () => root.render(<ProcessingVisual phase="C5" paused />));
  expect(
    container.querySelector('[data-phase="C5"][data-paused="true"]'),
  ).not.toBeNull();
});
