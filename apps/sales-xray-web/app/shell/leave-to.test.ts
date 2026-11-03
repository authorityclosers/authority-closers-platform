import { expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ leaving: vi.fn() }));
vi.mock("../ui/back-close", () => ({ leavingOverlay: calls.leaving }));

import { leaveTo } from "./leave-to";

// Simulation lab, 3 Nov 2026: a lead found in the search from Home closed the
// search and stayed on Home. The move says it is leaving before it goes, so
// the search closing doesn't step back over the new page.
it("says it is leaving the overlay before it moves", () => {
  const push = vi.fn();
  leaveTo("/leads?lead=one", { push });
  expect(push).toHaveBeenCalledWith("/leads?lead=one");
  expect(calls.leaving).toHaveBeenCalledTimes(1);
  expect(calls.leaving.mock.invocationCallOrder[0]).toBeLessThan(
    push.mock.invocationCallOrder[0],
  );
});
