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

it("shows truthful phase-aware thinking copy without inventing progress", async () => {
  await act(async () =>
    root.render(<ProcessingVisual phase="C4" paused={false} />),
  );
  expect(container.textContent).toContain("Reading the conversation");
  expect(container.textContent).toContain("Checking source evidence");
  expect(container.querySelectorAll("span")).toHaveLength(3);
});
