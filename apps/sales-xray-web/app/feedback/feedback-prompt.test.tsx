import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/leads" }));
vi.mock("../bug-report/device", () => ({
  reportContext: async () => ({
    app: { channel: "web", release: "abc123" },
    device: { viewport: "390x844" },
  }),
}));
const askStoreReview = vi.fn(async () => true);
vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => false,
  askStoreReview: () => askStoreReview(),
}));
vi.mock("../leads/leads-client", () => ({ peekPendingCall: () => null }));

import { askFeedback } from "./ask";
import { FeedbackCard, FeedbackHost } from "./feedback-prompt";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

const pause = (ms: number) =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });

beforeEach(() => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path === "/v1/feedback/state") {
      return new Response(
        JSON.stringify({
          opted_out: [],
          last: {},
          asked_today: 0,
          asked_this_week: 0,
          subjects: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({ feedback_id: "f-1" }), {
      status: 201,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetcher);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  document
    .querySelectorAll("dialog, main")
    .forEach((element) => element.remove());
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

/** Each test with a fake clock starts a day after the last, so no earlier touch counts. */
let clock = Date.UTC(2026, 9, 24, 10);
function fakeClock() {
  clock += 86_400_000;
  vi.useFakeTimers({ now: clock });
}

/** Fake time passing (the host waits in steps of half a second). */
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

function boxAt(
  left: number,
  top: number,
  right: number,
  bottom: number,
): DOMRect {
  return {
    x: left,
    y: top,
    left,
    top,
    right,
    bottom,
    width: right - left,
    height: bottom - top,
    toJSON: () => ({}),
  };
}

/** The card's place on a 390 x 844 phone: above the tab bar, full width less 12 px. */
function placeStack() {
  const stack = host.querySelector<HTMLElement>("[data-feedback-stack]")!;
  stack.getBoundingClientRect = () => boxAt(12, 750, 378, 750);
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find(
    (item) =>
      item.textContent?.trim() === label ||
      item.getAttribute("aria-label") === label,
  );
  if (!found) throw new Error(`no button ${label}`);
  return found;
}

function posted(): Record<string, unknown>[] {
  return fetcher.mock.calls
    .filter(
      ([input, init]) =>
        String(input) === "/v1/feedback" && init?.method === "POST",
    )
    .map(([, init]) => JSON.parse(String(init?.body)));
}

it("Great says thanks and sends the rating with the moment and what it is about", async () => {
  const done = vi.fn();
  await act(async () =>
    root.render(
      <FeedbackCard
        ask={{ moment: "report_read", subject: "call:1" }}
        onDone={done}
      />,
    ),
  );
  expect(host.textContent).toContain("How useful was this Report?");
  await act(async () => button("Great").click());
  await pause(20);
  expect(host.textContent).toContain("Thanks. That helps us make it better.");
  expect(posted()).toEqual([
    expect.objectContaining({
      moment: "report_read",
      kind: "rating",
      rating: 3,
      comment: null,
      subject: "call:1",
    }),
  ]);
  await pause(2500);
  expect(done).toHaveBeenCalled();
  // Not in the phone app: no Play Store card.
  expect(askStoreReview).not.toHaveBeenCalled();
});

it("Not good asks what would be better, and sends the words with the rating", async () => {
  await act(async () =>
    root.render(
      <FeedbackCard ask={{ moment: "call_outcome" }} onDone={() => {}} />,
    ),
  );
  await act(async () => button("Not good").click());
  expect(host.textContent).toContain("What would make it better?");
  expect(posted()).toEqual([]);
  const area = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(area, "The outcome list is too long");
    area.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Send").click());
  await pause(20);
  expect(posted()).toEqual([
    expect.objectContaining({
      moment: "call_outcome",
      rating: 1,
      comment: "The outcome list is too long",
    }),
  ]);
});

it("Not now and Don't ask again are answers too", async () => {
  const done = vi.fn();
  await act(async () =>
    root.render(<FeedbackCard ask={{ moment: "chats_used" }} onDone={done} />),
  );
  await act(async () => button("Don't ask about this again").click());
  await pause(20);
  expect(posted()).toEqual([
    expect.objectContaining({
      moment: "chats_used",
      kind: "opt_out",
      rating: null,
    }),
  ]);
  expect(done).toHaveBeenCalled();
  await act(async () =>
    root.render(
      <FeedbackCard key="2" ask={{ moment: "general" }} onDone={done} />,
    ),
  );
  await act(async () => button("Not now").click());
  await pause(20);
  expect(posted().at(-1)).toEqual(
    expect.objectContaining({ moment: "general", kind: "dismissed" }),
  );
});

it("asks only when nothing is in the way, and only as often as the rules allow", async () => {
  fakeClock();
  await act(async () => root.render(<FeedbackHost />));
  // A sheet is open: the question waits.
  const sheet = document.createElement("dialog");
  document.body.append(sheet);
  sheet.setAttribute("open", "");
  await act(async () => askFeedback("call_outcome"));
  await advance(9000);
  expect(host.textContent).not.toContain("How easy was logging that call?");
  sheet.remove();
  await advance(1000);
  expect(host.textContent).toContain("How easy was logging that call?");
  await act(async () => button("Not now").click());
  await advance(50);
  // Once today is the most: a second moment is not asked.
  await act(async () => askFeedback("chats_used"));
  await advance(10_000);
  expect(host.textContent).not.toContain("How are Chats working for you?");
});

it("never asks at once: waits until the result has been seen and left for a few seconds", async () => {
  fakeClock();
  await act(async () => root.render(<FeedbackHost />));
  await act(async () => askFeedback("plan_purchase"));
  await advance(3000);
  expect(host.textContent).not.toContain("How was buying your plan?");
  // A touch starts the wait again.
  await act(async () => document.body.dispatchEvent(new Event("pointerdown")));
  await advance(5000);
  expect(host.textContent).not.toContain("How was buying your plan?");
  await advance(1500);
  expect(host.textContent).toContain("How was buying your plan?");
});

it("never covers a button: waits on Payment confirmed, then asks on the next screen", async () => {
  fakeClock();
  const page = document.createElement("main");
  page.id = "main-content";
  document.body.append(page);
  window.history.replaceState(null, "", "/plans/return");
  await act(async () => root.render(<FeedbackHost />));
  placeStack();
  // Payment confirmed's actions sit where the card would.
  const action = document.createElement("a");
  action.href = "/new-analysis";
  action.textContent = "Analyse a call";
  action.getBoundingClientRect = () => boxAt(16, 640, 374, 688);
  page.append(action);
  await act(async () => askFeedback("plan_purchase"));
  await advance(30_000);
  expect(host.textContent).not.toContain("How was buying your plan?");

  // The person taps through to the next screen; a list's rows there may sit
  // under the card (they scroll), but a button would still hold it back.
  await act(async () => document.body.dispatchEvent(new Event("pointerdown")));
  action.remove();
  window.history.replaceState(null, "", "/new-analysis");
  const list = document.createElement("ul");
  const row = document.createElement("li");
  const open = document.createElement("button");
  open.textContent = "Open lead";
  open.getBoundingClientRect = () => boxAt(16, 660, 374, 720);
  row.append(open);
  list.append(row);
  page.append(list);
  await advance(1000);
  expect(host.textContent).not.toContain("How was buying your plan?");
  await advance(1500);
  expect(host.textContent).toContain("How was buying your plan?");
  // The page gets room at its end while the card shows, and loses it after.
  expect(page.querySelector("[data-feedback-room]")).not.toBeNull();
  await act(async () => button("Not now").click());
  await advance(50);
  expect(page.querySelector("[data-feedback-room]")).toBeNull();
});
