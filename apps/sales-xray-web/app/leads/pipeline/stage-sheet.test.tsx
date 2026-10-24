// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../../notice-center", () => ({ notify: () => undefined }));
vi.mock("../../telemetry", () => ({
  track: () => undefined,
  waitBand: () => "unknown",
}));

import type { MoveOption } from "./pipeline-client";
import { StageSheet, missing, moveInput, type Draft } from "./stage-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const option = (
  step: string,
  label: string,
  group: MoveOption["group"],
  needs: MoveOption["needs"],
  extra: Partial<MoveOption> = {},
): MoveOption => ({
  step,
  label,
  kind: step,
  group,
  action: group === "active" ? "move" : "close",
  needs,
  asks: group === "active" ? ["note"] : ["confirm", "note"],
  reasons: [],
  ...extra,
});

// Where a New lead may go in the sales team's nine stages.
const FROM_NEW: MoveOption[] = [
  option("not_connected", "Not Connected", "active", ["nc_reason"]),
  option("interested", "Interested (In Follow-Up)", "active", ["next_action"]),
  option("discussion_incomplete", "Discussion Incomplete", "active", [
    "next_action",
  ]),
  option("meeting_scheduled", "Meeting / Demo Scheduled", "active", [
    "meeting",
  ]),
  option("lost", "Closed / Lost", "lost", ["reason"], {
    reasons: [
      { key: "price", label: "Price or budget" },
      { key: "other", label: "Other" },
    ],
  }),
  option("junk", "Junk Lead", "junk", ["reason"], {
    reasons: [{ key: "fake", label: "Fake enquiry" }],
  }),
];
const LEAD = {
  lead_id: "00000000-0000-4000-9000-000000000001",
  revision: 3,
  name: "Asha Fictional",
  stage_label: "New Lead",
};
const BLANK: Draft = {
  when: null,
  custom: "",
  reason: null,
  reasonNote: "",
  ncReason: null,
  note: "",
  meeting: { pick: null, custom: "", mode: null, link: "", location: "" },
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

const buttons = () =>
  Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
const press = (text: string) =>
  act(() =>
    buttons()
      .find((button) => button.textContent?.trim() === text)
      ?.click(),
  );

it("lists only the moves the stage list allows, open stages first", () => {
  act(() =>
    root.render(
      <StageSheet
        open
        lead={LEAD}
        moves={FROM_NEW}
        onClose={() => {}}
        onMoved={() => {}}
      />,
    ),
  );
  const labels = Array.from(document.querySelectorAll("section li button")).map(
    (node) => node.querySelector("span")?.textContent,
  );
  expect(labels).toEqual([
    "Not Connected",
    "Interested (In Follow-Up)",
    "Discussion Incomplete",
    "Meeting / Demo Scheduled",
    "Closed / Lost",
    "Junk Lead",
  ]);
  expect(document.body.textContent).not.toContain("Closed / Won");
});

it("asks only what the move needs, and names what it does", () => {
  act(() =>
    root.render(
      <StageSheet
        open
        lead={LEAD}
        moves={FROM_NEW}
        initial="lost"
        onClose={() => {}}
        onMoved={() => {}}
      />,
    ),
  );
  const text = document.body.textContent ?? "";
  expect(text).toContain("Why was it lost?");
  expect(text).not.toContain("When is the meeting?");
  expect(text).not.toContain("Next follow-up");
  const close = buttons().find(
    (button) => button.textContent === "Close as Lost",
  );
  expect(close?.disabled).toBe(true);
  press("Price or budget");
  expect(close?.disabled).toBe(false);
});

it("sends the move with only what was asked", async () => {
  const sent: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({
        url,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      return new Response(JSON.stringify({ lead: { lead_id: LEAD.lead_id } }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  const moved = vi.fn();
  act(() =>
    root.render(
      <StageSheet
        open
        lead={LEAD}
        moves={FROM_NEW}
        initial="junk"
        onClose={() => {}}
        onMoved={moved}
      />,
    ),
  );
  press("Fake enquiry");
  await act(async () => {
    buttons()
      .find((button) => button.textContent === "Mark as Junk")
      ?.click();
  });
  const move = sent.find((item) => item.url.endsWith("/stage"));
  expect(move?.body).toMatchObject({
    expectedRevision: 3,
    step: "junk",
    reason: "fake",
    via: "sheet",
  });
  expect(move?.body).not.toHaveProperty("nextActionAt");
  expect(moved).toHaveBeenCalled();
});

it("knows what a move still lacks", () => {
  const meeting = FROM_NEW[3];
  expect(missing(meeting, BLANK)).toEqual(["meeting"]);
  const booked: Draft = {
    ...BLANK,
    meeting: {
      pick: "tomorrow_11",
      custom: "",
      mode: "zoom",
      link: "",
      location: "",
    },
  };
  expect(missing(meeting, booked)).toEqual([]);
  expect(moveInput(meeting, booked).meeting?.mode).toBe("zoom");
  const lost = FROM_NEW[4];
  expect(missing(lost, { ...BLANK, reason: "other" })).toEqual(["reason_note"]);
  expect(
    missing(lost, { ...BLANK, reason: "other", reasonNote: "Moved away" }),
  ).toEqual([]);
});
