// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { normalizeLabels } from "./labels-data";
import { ReviewPanel } from "./review-panel";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh, push: vi.fn() }),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
const fetcher = vi.fn();
beforeEach(() => {
  refresh.mockReset();
  fetcher
    .mockReset()
    .mockResolvedValue(Response.json({ id: "new" }, { status: 201 }));
  vi.stubGlobal("fetch", fetcher);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const render = () =>
  act(async () =>
    root.render(
      <ReviewPanel
        recordingId="rec-1"
        runId="run-1"
        labels={normalizeLabels({
          review_state: "new",
          effective: [],
          history: [],
        })}
      />,
    ),
  );
const key = (value: string) =>
  act(async () => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: value, bubbles: true }),
    );
  });
const sent = () =>
  fetcher.mock.calls.map(([url, init]) => [url, JSON.parse(init.body)]);

it("judges sections from the keyboard and saves each verdict as a new label", async () => {
  await render();
  await key("3");
  await key("ArrowDown");
  await key("1");
  expect(sent()).toEqual([
    [
      "/v1/admin/conversation/calls/rec-1/labels",
      {
        kind: "verdict",
        run_id: "run-1",
        section: "pillar:overview",
        value: { verdict: "wrong" },
      },
    ],
    [
      "/v1/admin/conversation/calls/rec-1/labels",
      {
        kind: "verdict",
        run_id: "run-1",
        section: "pillar:moments",
        value: { verdict: "correct" },
      },
    ],
  ]);
  const keys = fetcher.mock.calls.map(([, init]) =>
    new Headers(init.headers).get("idempotency-key"),
  );
  expect(new Set(keys).size).toBe(2);
  expect(refresh).toHaveBeenCalled();
  expect(
    host.querySelector(
      '[aria-label="Verdict on 1. The Big Picture"] [aria-pressed="true"]',
    )?.textContent,
  ).toBe("Wrong");
});

it("adds notes, marks data use and finishes the review", async () => {
  await render();
  const note = host.querySelector<HTMLTextAreaElement>(
    'textarea[aria-label="Note about this call"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(note, "Outcome is right");
    note.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "Add note")!
      .click(),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "Test data")!
      .click(),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "Mark review done")!
      .click(),
  );
  expect(sent().map(([, body]) => body)).toEqual([
    { kind: "note", value: { text: "Outcome is right" } },
    { kind: "data_use", value: { use: "test" } },
    { kind: "status", value: { state: "done" } },
  ]);
});

it("shows the API's refusal and does not keep a failed verdict", async () => {
  fetcher.mockResolvedValueOnce(
    Response.json(
      { detail: "Use the AC operations workspace." },
      { status: 403 },
    ),
  );
  await render();
  await key("2");
  expect(host.textContent).toContain("Use the AC operations workspace.");
  expect(
    host.querySelector(
      '[aria-label="Verdict on 1. The Big Picture"] [aria-pressed="true"]',
    ),
  ).toBeNull();
});
