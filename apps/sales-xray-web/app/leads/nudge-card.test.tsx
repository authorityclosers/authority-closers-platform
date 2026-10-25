// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const raised = vi.fn();
vi.mock("../ui/alerts", () => ({ raiseAlert: (a: unknown) => raised(a) }));

import { useNudgeCard } from "./nudge-card";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const start = vi.fn();

function Page() {
  useNudgeCard(start);
  return null;
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            title: "Back to your calls",
            body: "You're 8 calls behind your pace. Priya Sample is due now.",
            url: "/leads?nudge=1",
            urgency: "urgent",
          }),
          { headers: { "content-type": "application/json" } },
        ),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  raised.mockClear();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

async function mount() {
  await act(async () => root.render(<Page />));
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

// Owner program, 25 Oct 2026: a drifting seller gets an urgent card back to work.
it("shows a nudge as the urgent card, once, with Start calling", async () => {
  window.history.replaceState(null, "", "/leads?nudge=1&tab=work");
  await mount();
  expect(raised).toHaveBeenCalledWith(
    expect.objectContaining({
      id: "nudge",
      level: "urgent",
      title: "Back to your calls",
      message: "You're 8 calls behind your pace. Priya Sample is due now.",
    }),
  );
  expect(window.location.search).toBe("?tab=work");
  (raised.mock.calls[0][0] as { action: { run: () => void } }).action.run();
  expect(start).toHaveBeenCalledOnce();
});

it("stays quiet on an ordinary visit", async () => {
  window.history.replaceState(null, "", "/leads");
  await mount();
  expect(fetch).not.toHaveBeenCalled();
  expect(raised).not.toHaveBeenCalled();
});
