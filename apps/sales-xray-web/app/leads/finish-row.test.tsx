// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { FinishRow } from "./finish-row";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  localStorage.clear();
});

const NOW = new Date("2026-11-01T10:00:00Z");
const calls = [
  {
    lead_id: "lead-1",
    name: "fictional asha",
    called_at: "2026-11-01T09:56:00Z",
    event_id: "call-1",
  },
  {
    lead_id: "lead-2",
    name: "fictional ravi",
    called_at: "2026-11-01T09:30:00Z",
    event_id: "call-2",
  },
];

// Competitor teardown 3 (1 Nov 2026): a call left without its answer stays
// pinned until it is answered or put away as "Didn't call".
it("pins the newest unanswered call until it is finished or put away", async () => {
  const onFinish = vi.fn();
  await act(async () =>
    root.render(<FinishRow calls={calls} onFinish={onFinish} now={NOW} />),
  );
  expect(host.textContent).toContain("Finish: Fictional Asha");
  expect(host.textContent).toContain(
    "called 4 min ago · How did it go? · 1 more",
  );
  const [open, away] = host.querySelectorAll("button");
  await act(async () => open.click());
  expect(onFinish).toHaveBeenCalledWith("lead-1");
  expect(away.getAttribute("aria-label")).toBe("Didn't call Fictional Asha");
  await act(async () => away.click());
  expect(host.textContent).toContain("Finish: Fictional Ravi");
  // Put away stays put away on this phone.
  act(() => root.unmount());
  root = createRoot(host);
  await act(async () =>
    root.render(<FinishRow calls={calls} onFinish={onFinish} now={NOW} />),
  );
  expect(host.textContent).not.toContain("Fictional Asha");
  await act(async () =>
    root.render(<FinishRow calls={[]} onFinish={onFinish} now={NOW} />),
  );
  expect(host.textContent).toBe("");
});
