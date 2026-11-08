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
// first in the list until it is answered or put away as "Didn't call".
it("pins the newest unanswered call until it is finished or put away", async () => {
  const onFinish = vi.fn();
  await act(async () =>
    root.render(<FinishRow calls={calls} onFinish={onFinish} now={NOW} />),
  );
  expect(host.textContent).toContain("Finish: Fictional Asha");
  expect(host.textContent).toContain(
    "Called 4 min ago · How did it go? · 1 more",
  );
  const [open, away] = host.querySelectorAll("button");
  // Two lines in the list's first card (Leads L1), then a plain "Didn't call".
  expect(open.querySelector("strong")?.textContent).toBe(
    "Finish: Fictional Asha",
  );
  expect(open.querySelector("span")?.textContent).toMatch(/^Called /);
  expect(away.textContent).toBe("Didn’t call");
  expect(away.querySelector("svg")).toBeNull();
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

// Phone QA, 3 Nov 2026: the dialler opened and closed with Back, no call, and
// the line said "called just now". A dial the phone hasn't shown says so.
it("says dialled, not called, when the phone saw no call", async () => {
  await act(async () =>
    root.render(
      <FinishRow
        calls={[
          { ...calls[0], called_at: "2026-11-01T09:59:40Z", phone_saw: false },
        ]}
        onFinish={vi.fn()}
        now={NOW}
      />,
    ),
  );
  expect(host.textContent).toContain("Dialled just now · Did you call?");
  expect(host.textContent).not.toContain("Called");
});

// QA robot 95abddab (3 Nov 2026): the line left the page while a lead was open
// and came back on close, and the list under it jumped. Held, it keeps its room.
it("keeps its room, unseen, while a lead is open", async () => {
  await act(async () =>
    root.render(<FinishRow calls={calls} onFinish={vi.fn()} now={NOW} held />),
  );
  const line = host.querySelector('[role="status"]');
  expect(line).not.toBeNull();
  expect(line?.hasAttribute("data-held")).toBe(true);
  expect(line?.getAttribute("aria-hidden")).toBe("true");
});
