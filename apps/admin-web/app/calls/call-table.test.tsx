// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { normalizeQueue } from "./call-data";
import { CallTable } from "./call-table";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const row = (id: string, engine?: unknown) => ({
  recording_id: id,
  uploaded_at: "2026-10-19T03:30:00Z",
  organisation: { id: "t1", name: "Fictional Org", kind: "customer" },
  rep: { person_id: "p1", label: "Fictional Rep", kind: "member" },
  status: "ready",
  duration_ms: 210_000,
  runs: 2,
  review: "new",
  ...(engine === undefined ? {} : { engine }),
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows each call's engine reads, current objects and a link to its map", async () => {
  const queue = normalizeQueue({
    items: [
      row("c0000000-0000-4000-8000-000000000001", {
        fast: "succeeded",
        deep: "failed",
        objects: 12,
      }),
      row("c0000000-0000-4000-8000-000000000002"),
    ],
  });
  // Older servers send no engine block: nothing ran, no objects.
  expect(queue.items[1].engine).toEqual({ fast: null, deep: null, objects: 0 });
  await act(async () => root.render(<CallTable items={queue.items} back="" />));
  const table = host.querySelector("table")!;
  const headers = [...table.querySelectorAll("thead th")].map((th) =>
    th.textContent?.trim(),
  );
  expect(headers).toEqual([
    "Call",
    "Uploaded",
    "Language",
    "Model · prompt",
    "Engine",
    "Objects",
    "Runs",
    "Analysis",
    "Review",
    "Analysis map",
  ]);
  const [first, second] = [...table.querySelectorAll("tbody tr")];
  expect(first.textContent).toContain("Fictional Org");
  expect(first.querySelector('[title="Fast read: succeeded"]')).not.toBeNull();
  expect(first.querySelector('[title="Deep read: failed"]')).not.toBeNull();
  expect(first.textContent).toContain("12");
  expect(
    first.querySelector(
      'a[href="/calls/c0000000-0000-4000-8000-000000000001/map"]',
    ),
  ).not.toBeNull();
  expect(second.querySelector('[title^="Fast read"]')).toBeNull();
  expect(second.textContent).not.toContain("Not recorded");
});
