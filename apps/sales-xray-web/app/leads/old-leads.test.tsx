// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { OldLeadsCheck, waitReason, type OldLeads } from "./old-leads";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const state = (more: Partial<OldLeads> = {}): OldLeads => ({
  check: {
    stages: [
      { word: "Warm", rows: 3, stage: null },
      { word: "Converted", rows: 1, stage: "won" },
    ],
    ready: false,
    dates_read_as: "dmy",
    undated: 2,
    campaigns: [],
  },
  stages: [
    {
      key: "won",
      label: "Won",
      kind: "won",
    } as OldLeads["stages"][number],
  ],
  chosen: { Converted: "won" },
  unplaced: 1,
  pick: () => undefined,
  error: null,
  ...more,
});

it("waits with one plain reason until every word has a stage", () => {
  expect(waitReason(state())).toBe("Pick a stage for 1 name");
  expect(waitReason(state({ unplaced: 2 }))).toBe("Pick a stage for 2 names");
  expect(waitReason(state({ unplaced: 0 }))).toBeNull();
  expect(waitReason(state({ check: null }))).toBe("Checking the file…");
});

it("lists each stage word, its rows, and how the dates read", async () => {
  await act(async () => root.render(<OldLeadsCheck state={state()} />));
  const text = container.textContent ?? "";
  expect(text).toContain("Stages in your file");
  expect(text).toContain("Warm");
  expect(text).toContain("3 rows");
  expect(text).toContain("Enquiry dates read as day/month/year.");
  expect(text).toContain(
    "2 rows have no date we can read: they keep the day they are brought in.",
  );
  expect(text).toContain("Nobody is given them");
});
