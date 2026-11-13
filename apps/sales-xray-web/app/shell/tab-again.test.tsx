import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { tabAgain, useTabAgain } from "./tab-again";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Probe({ onAgain }: { onAgain: () => void }) {
  useTabAgain("leads", onAgain);
  return null;
}

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

// Redmi QA N1 (10 Nov 2026): the Leads tab on a lead's page did nothing. The
// tab tapped again is heard by its page, and only by its own.
it("tells the page its own tab was tapped again", async () => {
  const again = vi.fn();
  await act(async () => root.render(<Probe onAgain={again} />));
  tabAgain("dashboard");
  expect(again).not.toHaveBeenCalled();
  tabAgain("leads");
  expect(again).toHaveBeenCalledTimes(1);
});
