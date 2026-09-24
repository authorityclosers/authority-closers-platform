import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { FindingEvidence } from "./finding-evidence";
import { ReportReadingProvider } from "./report-reading-context";

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

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

it("shows source evidence in reading view and collapses it in tab view", async () => {
  const render = (reading: boolean) =>
    root.render(
      <ReportReadingProvider reading={reading}>
        <FindingEvidence count={1}>
          <blockquote>Full source quote.</blockquote>
        </FindingEvidence>
      </ReportReadingProvider>,
    );

  await act(async () => render(true));
  const evidence = container.querySelector("details")!;
  expect(evidence.open).toBe(true);
  expect(evidence.textContent).toContain("Full source quote.");

  await act(async () => render(false));
  expect(evidence.open).toBe(false);
});
