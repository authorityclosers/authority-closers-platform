// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const placed = vi.hoisted(() => ({
  marked: [] as string[],
  undone: [] as string[],
  refuse: null as Error | null,
}));
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  markDialNotPlaced: async (eventId: string) => {
    if (placed.refuse) throw placed.refuse;
    placed.marked.push(eventId);
    return {};
  },
  undoDialNotPlaced: async (eventId: string) => {
    placed.undone.push(eventId);
    return {};
  },
}));
const cards = vi.hoisted(() => ({
  shown: [] as {
    tone: string;
    title: string;
    message?: string;
    action?: { label: string; run: () => void };
  }[],
}));
vi.mock("../notice-center", () => ({
  notify: (card: (typeof cards.shown)[number]) => cards.shown.push(card),
}));

import { FinishRow, readGone } from "./finish-row";
import { LeadsError } from "./leads-client";

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
  placed.marked = [];
  placed.undone = [];
  placed.refuse = null;
  cards.shown = [];
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
  // Never placed, for the server too (Redmi QA, 13 Nov 2026).
  expect(placed.marked).toEqual(["call-1"]);
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

const flush = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

// Redmi QA on production 1.57 (13 Nov 2026): "Didn't call" said nothing and
// couldn't be taken back. A corner card says so, as Done does, and its Undo
// brings the call back, for the server too.
it("confirms Didn't call in a corner card whose Undo brings the call back", async () => {
  await act(async () =>
    root.render(<FinishRow calls={calls} onFinish={vi.fn()} now={NOW} />),
  );
  await act(async () => host.querySelectorAll("button")[1].click());
  await flush();
  expect(host.textContent).toContain("Finish: Fictional Ravi");
  const [card] = cards.shown;
  expect(card).toMatchObject({
    tone: "success",
    title: "Didn't call: Fictional Asha",
    message: "Not counted as a call.",
  });
  expect(card.action?.label).toBe("Undo");
  await act(async () => card.action?.run());
  await flush();
  expect(placed.undone).toEqual(["call-1"]);
  expect(host.textContent).toContain("Finish: Fictional Asha");
  // Taken back on this phone too, so Home's Pending action counts it again.
  expect(readGone()).toEqual([]);
});

// A dial the phone logged was placed: the server refuses, and the call waits
// for its answer again, with the server's reason in an error card.
it("brings the call back when the server refuses Didn't call", async () => {
  placed.refuse = new LeadsError(
    "Your phone logged this call, so it was placed.",
    409,
  );
  await act(async () =>
    root.render(<FinishRow calls={calls} onFinish={vi.fn()} now={NOW} />),
  );
  await act(async () => host.querySelectorAll("button")[1].click());
  await flush();
  expect(host.textContent).toContain("Finish: Fictional Asha");
  expect(cards.shown).toEqual([
    expect.objectContaining({
      tone: "error",
      title: "Not put away",
      message: "Your phone logged this call, so it was placed.",
    }),
  ]);
  expect(readGone()).toEqual([]);
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
