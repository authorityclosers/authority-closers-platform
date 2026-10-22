// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => [] as { title?: string; tone?: string }[]);
vi.mock("../notice-center", () => ({
  notify: (notice: { title?: string; tone?: string }) => notices.push(notice),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { BulkSheet } from "./bulk-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let sent: { url: string; body: Record<string, unknown> | undefined }[];
const SELLER = "00000000-0000-4000-8000-000000000002";

beforeEach(() => {
  notices.length = 0;
  sent = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (url === "/v1/lead-desk/team")
        return Response.json({
          reps: [
            {
              person_id: SELLER,
              name: "swamini fictional",
              open_leads: 12,
              available: true,
            },
          ],
        });
      if (url === "/v1/lead-desk/journey")
        return Response.json({
          stages: [
            { key: "new", label: "New enquiry", kind: "new", archived: false },
            {
              key: "not_connected",
              label: "Couldn't reach",
              kind: "not_connected",
              archived: false,
            },
            {
              key: "counselled",
              label: "Counselled",
              kind: "follow_up",
              archived: false,
            },
          ],
        });
      if (url === "/v1/lead-desk/leads/bulk")
        return Response.json({
          done: 2,
          skipped: 0,
          words: "2 leads moved to Counselled.",
        });
      return Response.json({ detail: "Not Found" }, { status: 404 });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  });
}
const press = (text: string) =>
  [...document.querySelectorAll("button")].find((button) =>
    button.textContent?.includes(text),
  )!;

it("gives the ticked leads to one person in one request", async () => {
  const done = vi.fn();
  await act(async () =>
    root.render(
      <BulkSheet
        open
        leadIds={["a", "b"]}
        pipeline={null}
        onClose={() => undefined}
        onDone={done}
      />,
    ),
  );
  await flush();
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("2 leads selected");
  // One pipeline: no pipeline move on offer.
  expect(dialog.textContent).not.toContain("Move to a pipeline");
  await act(async () => press("Give to a person").click());
  await flush();
  expect(dialog.textContent).toContain("Swamini Fictional");
  await act(async () => press("Swamini Fictional").click());
  await flush();
  const bulk = sent.find((item) => item.url === "/v1/lead-desk/leads/bulk");
  expect(bulk?.body).toMatchObject({
    action: "assign",
    person_id: SELLER,
    lead_ids: ["a", "b"],
  });
  expect(done).toHaveBeenCalled();
});

it("moves them to one of the stages, never to Couldn't reach", async () => {
  await act(async () =>
    root.render(
      <BulkSheet
        open
        leadIds={["a", "b"]}
        pipeline={null}
        onClose={() => undefined}
        onDone={() => undefined}
      />,
    ),
  );
  await flush();
  await act(async () => press("Move to a stage").click());
  await flush();
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("Counselled");
  expect(dialog.textContent).not.toContain("Couldn't reach");
  await act(async () => press("Counselled").click());
  await flush();
  expect(
    sent.find((item) => item.url === "/v1/lead-desk/leads/bulk")?.body,
  ).toMatchObject({ action: "stage", step: "counselled" });
  expect(notices).toEqual([
    expect.objectContaining({
      tone: "success",
      title: "2 leads moved to Counselled.",
    }),
  ]);
});
