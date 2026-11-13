// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { LeadPageFrame } from "./lead-page-frame";
import { openerAt, setLeadOpener } from "./lead-opener";

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
  setLeadOpener(null);
});

// Redmi QA batch 6 (13 Nov 2026): a call opened from Calls, and the lead's
// Back read "Back to Leads". It names the page it goes back to.
it("names Calls as the lead's Back while Calls opened it", async () => {
  expect(openerAt("/analysis/calls")).toEqual({
    path: "/analysis/calls",
    name: "Calls",
  });
  expect(openerAt("/leads")).toBeNull();
  expect(openerAt(null)).toBeNull();
  await act(async () =>
    root.render(
      <LeadPageFrame open label="Fictional Asha" onClose={() => undefined}>
        <p>Lead</p>
      </LeadPageFrame>,
    ),
  );
  const back = () =>
    document
      .querySelector("[data-lead-page] button")
      ?.getAttribute("aria-label");
  expect(back()).toBe("Back to Leads");
  await act(async () => setLeadOpener(openerAt("/analysis/calls")));
  expect(back()).toBe("Back to Calls");
  await act(async () => setLeadOpener(null));
  expect(back()).toBe("Back to Leads");
});
