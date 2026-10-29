// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { parseInsights } from "./insights-data";
import { OutcomeStory } from "./insights-outcomes";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
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
});
const body = {
  totals: { calls: 100, next_step: 75, won: 10 },
  previous: { won: 8 },
  pending: 3,
  outcomes: [
    { outcome: "won", calls: 10 },
    { outcome: "booked", calls: 25 },
    { outcome: "follow_up", calls: 40 },
    { outcome: "lost", calls: 25 },
    { outcome: "deferred", calls: 0 },
    { outcome: "disqualified", calls: 0 },
    { outcome: "unclear", calls: 0 },
  ],
};
it("reconciles nested counts and draws seven exact, directly labelled outcomes on one scale", () => {
  act(() =>
    root.render(<OutcomeStory data={parseInsights(body)} onCalls={() => {}} />),
  );
  expect(host.textContent).toContain("2 more won calls");
  expect(
    host
      .querySelector('[aria-label="Counted call funnel"] svg')
      ?.getAttribute("aria-label"),
  ).toContain("75 agreed a next step, including 10 won. 25 other endings");
  const rows = host.querySelectorAll('[aria-label="Calls by outcome"] button');
  expect(rows).toHaveLength(7);
  // Owner bug #78: a storage-style strip and a legend, grouped by next step.
  expect(rows[0].textContent).toBe("Follow-up set4040%");
  expect(
    host.querySelector<HTMLElement>('[role="img"] [data-outcome="follow_up"]')
      ?.style.flexGrow,
  ).toBe("40");
  expect(
    host.querySelector('[role="img"] [data-outcome="unclear"]'),
  ).toBeNull();
  expect(host.textContent).toContain(
    "Follow-up set was the most common ending",
  );
  expect(host.textContent).toContain("Agreed a next step75");
  expect(host.textContent).toContain("Other endings25");
  expect(host.textContent).toContain("3 pending");
  expect(rows[6].textContent).toBe("No clear next step00%");
});
it("keeps missing fields as dashes rather than creating zero outcomes or a funnel", () => {
  act(() =>
    root.render(
      <OutcomeStory
        data={parseInsights({
          totals: { calls: 10 },
          outcomes: [{ outcome: "lost", calls: 0 }],
        })}
        onCalls={() => {}}
      />,
    ),
  );
  expect(host.textContent).toContain("Next-step share unavailable");
  expect(host.textContent).toContain("Funnel counts unavailable");
  expect(host.textContent).toContain("Lost00%");
  expect(host.textContent).toContain("How every call ended");
  expect(host.textContent).toContain("Won—");
});
it("opens the exact outcome, and treats a real zero as zero", () => {
  const onCalls = vi.fn();
  act(() =>
    root.render(<OutcomeStory data={parseInsights(body)} onCalls={onCalls} />),
  );
  act(() =>
    host
      .querySelectorAll<HTMLButtonElement>(
        '[aria-label="Calls by outcome"] button',
      )[6]
      .click(),
  );
  expect(onCalls).toHaveBeenCalledWith("unclear");
  act(() =>
    root.render(
      <OutcomeStory
        data={parseInsights({ totals: { calls: 0, next_step: 0, won: 0 } })}
        onCalls={onCalls}
      />,
    ),
  );
  expect(
    host
      .querySelector('[aria-label="Counted call funnel"] svg')
      ?.getAttribute("aria-label"),
  ).toContain("0 analysed calls");
});
