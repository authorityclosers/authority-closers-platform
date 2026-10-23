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
  document.querySelectorAll("dialog").forEach((dialog) => dialog.remove());
  vi.unstubAllGlobals();
});

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
  await act(async () => root.render(<FeedbackHost />));
  // A sheet is open: the question waits.
  const sheet = document.createElement("dialog");
  document.body.append(sheet);
  sheet.setAttribute("open", "");
  await act(async () => askFeedback("call_outcome"));
  await pause(1600);
  expect(host.textContent).not.toContain("How easy was logging that call?");
  sheet.remove();
  await pause(1300);
  expect(host.textContent).toContain("How easy was logging that call?");
  await act(async () => button("Not now").click());
  await pause(20);
  // Once today is the most: a second moment is not asked.
  await act(async () => askFeedback("chats_used"));
  await pause(1500);
  expect(host.textContent).not.toContain("How are Chats working for you?");
});
