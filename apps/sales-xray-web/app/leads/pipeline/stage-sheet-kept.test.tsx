// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => [] as { tone: string; title: string }[]);
vi.mock("../../notice-center", () => ({
  notify: (notice: { tone: string; title: string }) => notices.push(notice),
}));
vi.mock("../../telemetry", () => ({
  track: () => undefined,
  waitBand: () => "unknown",
}));
// The phone kept the move (durable sync, 41b2e08d): the server hasn't answered yet.
vi.mock("./pipeline-client", async (original) => {
  const { LeadsError } = await import("../leads-client");
  return {
    ...(await original<typeof import("./pipeline-client")>()),
    moveLead: () => Promise.reject(new LeadsError("Not sent yet.", 0, true)),
  };
});

import { CARDS } from "../../review-fixture/lead-pipeline/lead-pipeline-data";
import type { MoveOption } from "./pipeline-client";
import { StageSheet } from "./stage-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const JUNK: MoveOption = {
  step: "junk",
  label: "Junk Lead",
  kind: "junk",
  group: "junk",
  action: "close",
  needs: ["reason"],
  asks: ["confirm", "note"],
  reasons: [{ key: "fake", label: "Fake enquiry" }],
};

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  notices.length = 0;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const click = (text: string) =>
  act(async () => {
    [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.trim() === text)
      ?.click();
  });

it("a move the phone kept is saved: the sheet closes and says so", async () => {
  const closed = vi.fn();
  act(() =>
    root.render(
      <StageSheet
        open
        lead={CARDS.new[0]}
        moves={[JUNK]}
        initial="junk"
        onClose={closed}
        onMoved={() => undefined}
      />,
    ),
  );
  await click("Fake enquiry");
  await click("Mark as Junk");
  expect(closed).toHaveBeenCalled();
  expect(notices.at(-1)).toMatchObject({
    tone: "info",
    title: "Saved on this phone",
  });
  expect(notices.some((notice) => notice.tone === "error")).toBe(false);
});
