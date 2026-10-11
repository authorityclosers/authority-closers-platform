// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { remainingAllowanceLabel } from "../../acquisition-studio";
import {
  CHECKING_ALLOWANCE,
  NewAnalysisSkeletonContent,
} from "./new-analysis-skeleton";

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

it("says what the studio says before its reads answer", () => {
  expect(CHECKING_ALLOWANCE).toBe(remainingAllowanceLabel(null, null, false));
});

it("draws the studio's own upload screen, busy, with the picker held", async () => {
  await act(async () => root.render(<NewAnalysisSkeletonContent />));
  const frame = host.querySelector('[role="status"]');
  expect(frame?.getAttribute("aria-busy")).toBe("true");
  expect(frame?.getAttribute("aria-label")).toBe("Loading New analysis");
  // The same wrappers and stage the loaded studio uses, so the boxes match.
  expect(frame?.getAttribute("data-variant")).toBe("standalone");
  expect(frame?.getAttribute("data-stage")).toBe("upload");
  expect(frame?.querySelector(".studio-main section.panel")).not.toBeNull();
  // The real heading, drop area and footer; only the picker waits.
  expect(host.textContent).toContain("analyse your next call");
  expect(host.textContent).toContain("Drop your call recording here");
  expect(host.textContent).toContain(CHECKING_ALLOWANCE);
  const choose = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Choose a file",
  );
  expect(choose?.disabled).toBe(true);
});
