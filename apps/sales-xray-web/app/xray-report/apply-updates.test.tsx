// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { MoveOption } from "../leads/pipeline/pipeline-client";
import { callTimeOf, moveFor, useCallLead } from "./apply-updates";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const move = (step: string, kind: string, action = "move"): MoveOption =>
  ({
    step,
    label: step,
    kind,
    group: kind === "won" ? "won" : kind === "lost" ? "lost" : "active",
    action,
    needs: [],
    asks: [],
    reasons: [],
  }) as unknown as MoveOption;

// Competitor teardown 24 (1 Nov 2026): a chip opens the lead page's own sheet,
// on the stage its list allows; nothing is written until Save.
it("matches a chip to the move its lead's list allows", () => {
  const moves = [
    move("interested", "interested"),
    move("won", "won"),
    move("lost_reopen", "lost", "reopen"),
  ];
  expect(
    moveFor(moves, { key: "stage", outcome: "won", label: "Mark Won" })?.step,
  ).toBe("won");
  // An amount is a Won deal's.
  expect(
    moveFor(moves, { key: "amount", amount: "2.5 L", label: "" })?.step,
  ).toBe("won");
  // No plain move to Lost on this list: no chip.
  expect(
    moveFor(moves, { key: "stage", outcome: "lost", label: "Mark Lost" }),
  ).toBeNull();
  expect(
    moveFor(moves, { key: "next_call", date: "2026-11-04", label: "" }),
  ).toBeNull();
});

it("reads the call's date as a time to call, 11 AM when it names no time", () => {
  expect(callTimeOf("2026-11-04")?.getHours()).toBe(11);
  expect(callTimeOf("2026-11-04T16:30:00")?.getHours()).toBe(16);
  expect(callTimeOf("someday")).toBeNull();
});

function Probe({ callId }: { callId: string | null }) {
  const [lead] = useCallLead(callId);
  return <p>{lead ? lead.lead.name : "none"}</p>;
}

it("asks for the call's lead once, and shows no lead when it isn't the viewer's", async () => {
  const fetched: string[] = [];
  let answer: unknown = {
    lead: { lead_id: "l1", name: "Fictional Asha", revision: 3 },
    can_edit: true,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      fetched.push(String(input));
      return new Response(JSON.stringify(answer), {
        headers: { "content-type": "application/json" },
      });
    }),
  );
  await act(async () => root.render(<Probe callId="sub-1" />));
  expect(host.textContent).toBe("Fictional Asha");
  expect(fetched).toEqual(["/v1/lead-desk/calls/sub-1/lead"]);
  answer = null;
  await act(async () => root.render(<Probe callId="sub-2" />));
  expect(host.textContent).toBe("none");
  await act(async () => root.render(<Probe callId={null} />));
  expect(fetched).toHaveLength(2);
});
