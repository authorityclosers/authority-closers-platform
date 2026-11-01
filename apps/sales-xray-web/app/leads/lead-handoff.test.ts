// @vitest-environment happy-dom
import { expect, it, vi } from "vitest";

import {
  LEAD_ADDED_EVENT,
  handOverLead,
  handOverRound,
  takeHandedLead,
  type HandedLead,
} from "./lead-handoff";

// Phone personas ph2-33 (1 Nov 2026): Start cold calling handed a lead over to
// be called at once, so the dialer opened before the seller saw the card.
it("hands over a round to start at its card, apart from a call to place now", () => {
  const heard: HandedLead[] = [];
  const listen = vi.fn((event: Event) =>
    heard.push((event as CustomEvent<HandedLead>).detail),
  );
  window.addEventListener(LEAD_ADDED_EVENT, listen);
  handOverRound("lead-1");
  expect(heard.at(-1)).toEqual({ leadId: "lead-1", call: false, round: true });
  expect(takeHandedLead()).toEqual({
    leadId: "lead-1",
    call: false,
    round: true,
  });
  expect(takeHandedLead()).toBeNull();
  handOverLead("lead-2", true);
  expect(takeHandedLead()).toEqual({ leadId: "lead-2", call: true });
  window.removeEventListener(LEAD_ADDED_EVENT, listen);
});
