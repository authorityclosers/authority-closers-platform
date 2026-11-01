// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("../notice-center", () => ({ notify }));
vi.mock("../bug-report/device", () => ({
  reportContext: async () => ({ viewport: "390x844" }),
}));

import { AiNotes, noteSuggestions, talkWords } from "./ai-notes";
import { exampleView } from "./example";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
let posted: Record<string, unknown>[];
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  posted = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string, init: RequestInit = {}) => {
      posted.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ feedback_id: "f1", bug_id: null }));
    }),
  );
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  notify.mockClear();
});

// Competitor teardown 24 (1 Nov 2026): Recap, Next step and Copy, each rated;
// suggested updates applied only with a tap; one line of talk numbers.
const real = () => ({ ...exampleView("won"), illustrative: false });

it("says the talk in one line, and suggests the stage, next call and amount", () => {
  expect(
    talkWords({ you: 62, yourLongestMs: 130_000, theirLongestMs: 65_000 }),
  ).toBe("You 62% · longest monologue 2:10 · their longest story 1:05");
  expect(
    talkWords({ you: null, yourLongestMs: null, theirLongestMs: null }),
  ).toBeNull();
  const view = real();
  const keys = noteSuggestions(view).map((item) => item.key);
  expect(keys).toContain("stage");
  expect(
    noteSuggestions(view).find((item) => item.key === "stage")?.label,
  ).toBe("Mark Won");
  expect(
    noteSuggestions({
      ...view,
      outcome: {
        ...view.outcome,
        kind: null,
        value: null,
        nextSteps: [],
        date: null,
      },
    }),
  ).toEqual([]);
});

it("copies the recap and next step, and sends a thumbs down with its words", async () => {
  const write = vi.fn(async () => {});
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: write },
    configurable: true,
  });
  const view = real();
  await act(async () =>
    root.render(<AiNotes view={view} callKey="call-1" talk={null} />),
  );
  expect(
    host.querySelector('[aria-label="Call summary"] h3')?.textContent,
  ).toBe("Call Summary");
  const copy = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Copy",
  )!;
  await act(async () => copy.click());
  expect(write).toHaveBeenCalledWith(expect.stringContaining("Recap: "));
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({ title: "Copied" }),
  );

  const down = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Not helpful"]',
  )!;
  await act(async () => down.click());
  expect(posted.at(-1)).toMatchObject({
    moment: "report_read",
    kind: "rating",
    rating: 1,
    subject: "ai_notes.recap:call-1",
  });
  const input = host.querySelector<HTMLInputElement>("form input")!;
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    set.call(input, "The amount was 2 lakh, not 12");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    host.querySelector<HTMLFormElement>("form")!.requestSubmit(),
  );
  expect(posted.at(-1)).toMatchObject({
    rating: 1,
    comment: "The amount was 2 lakh, not 12",
  });
  expect(host.textContent).toContain("Thanks. The team will look at it.");
});

it("offers Apply only where the page knows the lead, and writes on a tap", async () => {
  const view = real();
  await act(async () => root.render(<AiNotes view={view} />));
  expect(host.querySelector('[aria-label="Suggested updates"]')).toBeNull();
  const apply = vi.fn(async () => {});
  await act(async () => root.render(<AiNotes view={view} onApply={apply} />));
  const chip = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Apply: Mark Won",
  )!;
  expect(apply).not.toHaveBeenCalled();
  await act(async () => chip.click());
  expect(apply).toHaveBeenCalledWith(
    expect.objectContaining({ key: "stage", outcome: "won" }),
  );
  expect(chip.textContent).toBe("Mark Won");
});

it("keeps a chip ready when its sheet closes unsaved, and shows only updates the lead can take", async () => {
  const view = real();
  const apply = vi.fn(async () => false);
  await act(async () =>
    root.render(
      <AiNotes
        view={view}
        onApply={apply}
        applicable={(suggestion) => suggestion.key !== "amount"}
      />,
    ),
  );
  const labels = [
    ...host.querySelectorAll('[aria-label="Suggested updates"] button'),
  ].map((button) => button.textContent);
  expect(labels).toContain("Apply: Mark Won");
  expect(labels.some((label) => label?.startsWith("Apply: Amount"))).toBe(
    false,
  );
  const chip = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Apply: Mark Won",
  )!;
  await act(async () => chip.click());
  // Backed out of the sheet: nothing written, the chip as it was, no error.
  expect(chip.textContent).toBe("Apply: Mark Won");
  expect(chip.disabled).toBe(false);
  expect(notify).not.toHaveBeenCalled();
});
