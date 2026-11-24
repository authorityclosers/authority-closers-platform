// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";

import { LeadOpeningSkeleton } from "./lead-opening-skeleton";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// v1.96 device polish, lane P: on slow 3G a returning seller saw a bare
// "Opening the lead…" for 7 s; the lead page's own outline shows at once.
it("draws the lead page's outline at once, busy, with its words for screen readers", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<LeadOpeningSkeleton />));
  const outline = host.querySelector("[data-lead-opening]");
  expect(outline?.getAttribute("aria-busy")).toBe("true");
  expect(outline?.textContent).toBe("Opening the lead…");
  // The head card, the four round actions and "Before you call".
  expect(host.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(
    10,
  );
  await act(async () => root.unmount());
  host.remove();
});
