// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  isPracticeResponseReady,
  PracticeArcade,
  PracticeQuestion,
} from "./practice-arcade";
import {
  PracticeRequestError,
  type PracticeApi,
  type PracticeCheckResult,
  type PracticePrompt,
} from "../lib/practice-api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const base = {
  id: "choice-01",
  prompt: "What would help clarify this concern?",
  hint: "Start by listening.",
};
const options = [
  { id: 1, text: "Offer a discount." },
  { id: 0, text: "Ask what is unclear." },
];
const choice: PracticePrompt = { ...base, kind: "choice", options };
const useful: PracticeCheckResult = {
  kind: "feedback",
  reference_match: true,
  explanation: "A question gives the buyer room to explain.",
  course_progress_affected: false,
  responses_stored: false,
};
let container: HTMLDivElement;
let root: Root;
let check: ReturnType<typeof vi.fn>;
let api: PracticeApi;
let next: ReturnType<typeof vi.fn<(revised: boolean) => void>>;
let unmounted = false;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
  check = vi.fn(async () => useful);
  next = vi.fn();
  api = { check, catalog: vi.fn(), set: vi.fn() } as unknown as PracticeApi;
});
afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});
async function mount(item: PracticePrompt = choice) {
  await act(async () =>
    root.render(
      <PracticeQuestion
        item={item}
        setId="next-move"
        api={api}
        onNext={next}
      />,
    ),
  );
}
function button(text: string) {
  const found = [
    ...container.querySelectorAll<HTMLButtonElement>("button"),
  ].find((b) => b.textContent?.trim() === text);
  expect(found, `button ${text}`).toBeTruthy();
  return found!;
}
async function click(element: HTMLElement) {
  await act(async () => element.click());
}

it("requires a choice, sends stable option ID, shows backend explanation, and advances only on request", async () => {
  await mount();
  expect(button("Check my response").disabled).toBe(true);
  expect(document.activeElement?.tagName).toBe("H1");
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Check my response"));
  expect(check).toHaveBeenCalledWith(
    "next-move",
    "choice-01",
    [0],
    expect.any(AbortSignal),
  );
  expect(container.textContent).toContain(useful.explanation);
  expect(document.activeElement?.getAttribute("role")).toBe("status");
  expect(next).not.toHaveBeenCalled();
  await click(button("Next prompt"));
  expect(next).toHaveBeenCalledWith(false);
});

it("keeps the response on network failure and retries without erasing choices", async () => {
  check.mockRejectedValueOnce(new TypeError("Network failed"));
  await mount();
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Check my response"));
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "choices are still here",
  );
  expect(
    container.querySelector<HTMLInputElement>('input[value="0"]')?.checked,
  ).toBe(true);
  await click(button("Check my response"));
  expect(check).toHaveBeenCalledTimes(2);
  expect(container.textContent).toContain("That’s a useful move");
});

it("supports revision after nonmatching feedback without claiming a score", async () => {
  check.mockResolvedValueOnce({ ...useful, reference_match: false });
  await mount();
  await click(container.querySelector<HTMLInputElement>('input[value="1"]')!);
  await click(button("Check my response"));
  expect(container.textContent).toContain(
    "Here’s a useful way to think about it",
  );
  await click(button("Try a different answer"));
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Check my response"));
  await click(button("Next prompt"));
  expect(next).toHaveBeenCalledWith(true);
  expect(container.textContent).not.toMatch(/XP|mastery|rank|streak/);
});

it("blocks double submit and ignores a late reply after unmount", async () => {
  let resolve!: (value: PracticeCheckResult) => void;
  check.mockReturnValue(
    new Promise<PracticeCheckResult>((r) => {
      resolve = r;
    }),
  );
  await mount();
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  const submit = button("Check my response");
  await act(async () => {
    submit.click();
    submit.click();
  });
  expect(check).toHaveBeenCalledTimes(1);
  const signal = check.mock.calls[0][3] as AbortSignal;
  await act(async () => root.unmount());
  unmounted = true;
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(useful));
  expect(next).not.toHaveBeenCalled();
  expect(container.innerHTML).toBe("");
});

it("lets matching pairs be changed and does not allow one right tile twice", async () => {
  await mount({
    ...base,
    kind: "match",
    left: [
      { id: 0, text: "Buyer A" },
      { id: 1, text: "Buyer B" },
    ],
    options,
  });
  const find = (text: string) =>
    [...container.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
      b.textContent?.includes(text),
    )!;
  expect(find("Ask what is unclear.").disabled).toBe(true);
  await click(find("Buyer A"));
  await click(find("Ask what is unclear."));
  await click(find("Buyer B"));
  await click(find("Ask what is unclear."));
  expect(button("Check my response").disabled).toBe(true);
  await click(find("Buyer A"));
  await click(find("Offer a discount."));
  await click(button("Check my response"));
  expect(check.mock.calls[0][2]).toEqual([1, 0]);
});

it.each(["build", "order"] as const)(
  "%s supports tap-to-add, undo, and full ordering",
  async (kind) => {
    await mount({ ...base, kind, options });
    await click(button("Ask what is unclear."));
    expect(button("Check my response").disabled).toBe(true);
    await click(button("Offer a discount."));
    await click(
      container.querySelector<HTMLButtonElement>(
        '[aria-label="Remove Ask what is unclear."]',
      )!,
    );
    expect(button("Check my response").disabled).toBe(true);
    await click(button("Ask what is unclear."));
    await click(button("Check my response"));
    expect(check.mock.calls[0][2]).toEqual([1, 0]);
  },
);

it("audio never autoplays and keeps the transcript available", async () => {
  await mount({
    ...base,
    kind: "audio",
    options,
    spoken: "I need my partner involved.",
    audio_url: "/arcade-v02/listen-01.wav",
  });
  const audio = container.querySelector("audio")!;
  expect(audio.autoplay).toBe(false);
  expect(audio.preload).toBe("none");
  expect(audio.controls).toBe(true);
  expect(container.querySelector("details")?.textContent).toContain(
    "I need my partner involved.",
  );
});

it("gap renders selected word and sends its index, not free text", async () => {
  await mount({
    ...base,
    kind: "gap",
    prompt: "First ____ the concern.",
    options,
  });
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  expect(container.querySelector("mark")?.textContent).toBe(
    "Ask what is unclear.",
  );
  await click(button("Check my response"));
  expect(check.mock.calls[0][2]).toEqual([0]);
});

it("branch walks server-provided nodes and submits the complete path", async () => {
  check.mockResolvedValueOnce({
    kind: "continue",
    node: {
      buyer: "That’s the concern.",
      options: [{ id: 0, text: "Explore the concern." }],
    },
  });
  await mount({
    ...base,
    kind: "branch",
    node: { buyer: "My partner is involved.", options },
  });
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Send response"));
  expect(container.textContent).toContain("That’s the concern.");
  expect(button("Send response").disabled).toBe(true);
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Send response"));
  expect(check.mock.calls[1][2]).toEqual([0, 0]);
});

it("a denied catalog shows sign-in without a placeholder library", async () => {
  api.catalog = vi.fn().mockRejectedValue(new PracticeRequestError(401));
  await act(async () => root.render(<PracticeArcade api={api} />));
  expect(container.querySelector('a[href="/login"]')).toBeTruthy();
  expect(container.textContent).not.toContain("8 sets");
});

it("response readiness rejects incomplete or duplicate arrangements", () => {
  const item: PracticePrompt = { ...base, kind: "order", options };
  expect(isPracticeResponseReady(item, [0])).toBe(false);
  expect(isPracticeResponseReady(item, [0, 0])).toBe(false);
  expect(isPracticeResponseReady(item, [0, 1])).toBe(true);
});

it("keeps actions outside the prompt scroll area and returns focus when revising", async () => {
  check.mockResolvedValueOnce({ ...useful, reference_match: false });
  await mount();
  const scroll = container.querySelector('[data-session-scroll="body"]')!;
  expect(scroll.contains(button("Check my response"))).toBe(false);
  expect(
    container.querySelector("footer")?.contains(button("Check my response")),
  ).toBe(true);
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Check my response"));
  expect(container.querySelectorAll('input[type="radio"]').length).toBe(0);
  expect(scroll.contains(button("Next prompt"))).toBe(false);
  await click(button("Try a different answer"));
  expect(document.activeElement?.tagName).toBe("H1");
  expect(
    container.querySelector<HTMLInputElement>('input[value="0"]')!.checked,
  ).toBe(true);
});
