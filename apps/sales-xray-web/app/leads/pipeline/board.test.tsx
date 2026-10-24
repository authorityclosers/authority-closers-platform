// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../../notice-center", () => ({ notify: () => undefined }));
vi.mock("../../telemetry", () => ({
  track: () => undefined,
  waitBand: () => "unknown",
}));

import { fixtureBoard } from "../../review-fixture/lead-pipeline/lead-pipeline-data";
import { PipelineBoard, moveCard } from "./board";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(fixtureBoard()), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function draw() {
  await act(async () => {
    root.render(
      <PipelineBoard
        filters={{ pipeline: "main" }}
        canManage
        onOpen={() => {}}
      />,
    );
  });
}

it("shows all nine stages, grouped, with each lead in one column", async () => {
  await draw();
  const columns = Array.from(container.querySelectorAll("section[data-step]"));
  expect(columns.map((column) => column.getAttribute("data-step"))).toEqual([
    "new",
    "not_connected",
    "interested",
    "discussion_incomplete",
    "meeting_scheduled",
    "demo_completed",
    "won",
    "lost",
    "junk",
  ]);
  const names = Array.from(
    container.querySelectorAll("li button[aria-label^='Open ']"),
  ).map((button) => button.getAttribute("aria-label"));
  expect(new Set(names).size).toBe(names.length);
  // Names with capitals; one line of where from and when; late and no next
  // step marked. No phone number on a card (owner, 24 Oct 2026: less clutter).
  expect(container.textContent).toContain("Asha Fictional");
  expect(container.textContent).toContain("Meta lead form");
  expect(container.textContent).not.toContain("••4301");
  expect(container.textContent).toContain("No next step");
  expect(container.textContent).not.toMatch(/₹|price list/i);
});

it("a card's Move opens the stage sheet with only that stage's moves", async () => {
  await draw();
  await act(async () => {
    container
      .querySelector<HTMLButtonElement>(
        "button[aria-label='Move Asha Fictional']",
      )
      ?.click();
  });
  const text = document.body.textContent ?? "";
  expect(text).toContain("Move Asha Fictional to…");
  expect(text).toContain("Meeting / Demo Scheduled");
  expect(document.querySelectorAll("dialog section li button").length).toBe(6);
});

it("a moved card leaves its column for the other, counts kept", () => {
  const board = fixtureBoard();
  const lead = board.groups[0].columns[0].cards[0];
  const after = moveCard(board, lead, "new", "not_connected");
  const columns = after.groups.flatMap((group) => group.columns);
  const before = board.groups.flatMap((group) => group.columns);
  expect(columns[0].cards.map((card) => card.lead_id)).not.toContain(
    lead.lead_id,
  );
  expect(columns[1].cards[0].lead_id).toBe(lead.lead_id);
  expect(columns[0].count).toBe(before[0].count - 1);
  expect(columns[1].count).toBe(before[1].count + 1);
  expect(after.groups[0].count).toBe(board.groups[0].count);
});
