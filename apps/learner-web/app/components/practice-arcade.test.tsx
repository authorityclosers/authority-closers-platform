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
  type PracticeSummary,
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

it("links to a separate academy leaderboard without coupling it to username claiming", async () => {
  vi.mocked(api.catalog).mockResolvedValue({
    items: [],
    mode: "editorial_preview",
    course_progress_affected: false,
    responses_stored: false,
  });
  await act(async () => root.render(<PracticeArcade api={api} durable />));
  const link = container.querySelector<HTMLAnchorElement>(
    'a[href="/leaderboard"]',
  );
  expect(link?.getAttribute("aria-label")).toBe("Academy leaderboard");
  expect(
    container.querySelector('a[href*="community-identity-title"]'),
  ).toBeNull();
});

it.each([
  [true, "success", "celebrate", "Nicely done!"],
  [false, "retry", "encourage", "Try another approach"],
  [null, "reflection", "ready", "A thoughtful next step"],
] as const)(
  "uses distinct truthful feedback for a %s reference match",
  async (match, tone, mood, title) => {
    check.mockResolvedValueOnce({ ...useful, reference_match: match });
    await mount();
    expect(container.querySelector("[data-feedback-tone]")).toBeNull();
    await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
    await click(button("Check my response"));
    const stage = container.querySelector(`[data-feedback-tone="${tone}"]`);
    expect(stage).not.toBeNull();
    expect(stage?.querySelector(`svg[data-mood="${mood}"]`)).not.toBeNull();
    expect(stage?.querySelector("h1")?.textContent).toBe(title);
    expect(stage?.textContent).toContain(useful.explanation);
    if (match === false) {
      expect(
        stage?.querySelector('[role="status"]')?.textContent,
      ).not.toContain(useful.explanation);
      const reference = stage?.querySelector("details");
      expect(reference?.querySelector("summary")?.textContent).toBe(
        "Reference explanation",
      );
      expect(reference?.open).toBe(false);
      expect(reference?.textContent).toContain(useful.explanation);
    }
    expect(stage?.querySelectorAll("i").length).toBe(match === true ? 12 : 0);
    expect(stage?.textContent).not.toMatch(/credits|XP|streak|score/);
    expect(next).not.toHaveBeenCalled();
  },
);

it("does not show a success reaction when checking fails", async () => {
  check.mockRejectedValueOnce(new TypeError("offline"));
  await mount();
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Check my response"));
  expect(container.querySelector("[data-feedback-tone]")).toBeNull();
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
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
  expect(container.textContent).toContain("Nicely done!");
});

it("supports revision after nonmatching feedback without claiming a score", async () => {
  check.mockResolvedValueOnce({ ...useful, reference_match: false });
  await mount();
  await click(container.querySelector<HTMLInputElement>('input[value="1"]')!);
  await click(button("Check my response"));
  expect(container.textContent).toContain("Try another approach");
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

async function mountCatalog(items: PracticeSummary[]) {
  api.catalog = vi.fn().mockResolvedValue({ items });
  await act(async () => root.render(<PracticeArcade api={api} />));
}

const catalogSet: PracticeSummary = {
  id: "custom-conversation",
  version: 1,
  title: "Find a useful question",
  kind: "branch",
  skill: "Discovery",
  description: "Listen, then choose your response.",
  art: "discovery-compass",
  color: "mint",
  estimated_minutes: 4,
  item_count: 5,
};

it("keeps game descriptions behind an accessible info action and returns focus on Escape", async () => {
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = true;
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.open = false;
  });
  await mountCatalog([catalogSet]);
  const card = container.querySelector("article")!;
  expect(card.textContent).not.toContain(catalogSet.description);
  const trigger = card.querySelector<HTMLButtonElement>(
    'button[aria-haspopup="dialog"]',
  )!;
  expect(trigger.closest("a")).toBeNull();
  await click(trigger);
  const dialog = container.querySelector<HTMLDialogElement>("dialog[open]")!;
  expect(trigger.getAttribute("aria-controls")).toBe(dialog.id);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  expect(
    document.getElementById(dialog.getAttribute("aria-describedby")!)
      ?.textContent,
  ).toBe(catalogSet.description);
  expect(dialog.querySelector("a")?.getAttribute("href")).toBe(
    `/practice?set=${catalogSet.id}`,
  );
  await act(async () =>
    dialog.dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  expect(container.querySelector("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(api.check).not.toHaveBeenCalled();
});

it("features only an available set and uses its real title and prompt count", async () => {
  await mountCatalog([catalogSet]);
  const featured = container.querySelector(
    '[aria-labelledby="practice-featured-title"]',
  )!;
  expect(featured.textContent).toContain(catalogSet.title);
  expect(featured.textContent).toContain("5 prompts");
  expect(featured.querySelector("a")?.getAttribute("href")).toBe(
    "/practice?set=custom-conversation",
  );
  expect(
    container.querySelector('a[href="/practice?set=next-move"]'),
  ).toBeNull();
  expect(container.textContent).not.toContain("Every set has three");
});

it("shows an honest empty library with a useful route instead of a dead start button", async () => {
  await mountCatalog([]);
  expect(container.textContent).toContain("Your next practice is on its way");
  expect(container.querySelector('a[href="/learning"]')).toBeTruthy();
  expect(container.querySelector('a[href^="/practice?set="]')).toBeNull();
});

it("keeps format labels beside decorative color and safely falls back for unknown colors", async () => {
  await mountCatalog([
    catalogSet,
    { ...catalogSet, id: "other", kind: "gap", color: "unrecognized" },
  ]);
  const cards = container.querySelectorAll("article[data-color]");
  expect(cards[0].getAttribute("data-color")).toBe("mint");
  expect(cards[0].querySelector("a")?.getAttribute("aria-label")).toContain(
    "Conversation",
  );
  expect(cards[1].getAttribute("data-color")).toBe("cobalt");
  expect(cards[1].querySelector("a")?.getAttribute("aria-label")).toContain(
    "Fill the gap",
  );
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
