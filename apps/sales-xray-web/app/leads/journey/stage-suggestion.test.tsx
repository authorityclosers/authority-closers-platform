import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";

import type { LeadDetail } from "../leads-client";
import { SuggestedStage } from "./stage-suggestion";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Tester report 209 (production 1.58, 14 Nov 2026): "From the last call" had a
// full-width filled "Move to Meeting Scheduled" right above the filled Call
// band, two equal primary buttons on one screen.
it("offers the last call's stage as an outlined button, never a second filled one", async () => {
  const detail = {
    lead: { id: "0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10" },
    can_edit: true,
    stage_suggestion: {
      kind: "forward",
      step: "meeting_scheduled",
      label: "Meeting Scheduled",
      why: "They asked to meet on Friday.",
    },
  } as unknown as LeadDetail;
  const host = document.createElement("div");
  const root = createRoot(host);
  await act(async () =>
    root.render(<SuggestedStage detail={detail} onChanged={() => {}} />),
  );
  const button = host.querySelector("button");
  expect(button?.textContent).toBe("Move to Meeting Scheduled");
  expect(button?.getAttribute("data-variant")).toBe("secondary");
  expect(host.querySelector('[data-variant="primary"]')).toBeNull();
  await act(async () => root.unmount());
});
