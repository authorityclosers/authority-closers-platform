import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadsTabIcon, publishBadge, useLeadsBadgeWords } from "./leads-badge";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  // Reads never answer here; the page hands over its counts instead.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

function LeadsLink() {
  const words = useLeadsBadgeWords(true);
  return (
    <a href="/leads" aria-label={`Leads${words}`}>
      <LeadsTabIcon live />
      <span>Leads</span>
    </a>
  );
}

// The test robot, 31 Oct 2026: a screen reader said "3, 3 late Leads". The
// link says the place first, then what waits; the badge is only seen.
it("names the link label first, with the badge hidden", async () => {
  await act(async () => root.render(<LeadsLink />));
  await act(async () => publishBadge({ overdue: 3, to_call: 8 }));
  const link = host.querySelector("a")!;
  // One count (#9 option A): the To Call list's 8 rows, red as 3 are late.
  expect(link.getAttribute("aria-label")).toBe("Leads, 8 to call, 3 late");
  const badge = link.querySelector("[data-tone]")!;
  expect(badge.getAttribute("aria-hidden")).toBe("true");
  expect(badge.textContent).toBe("8");
  expect(badge.getAttribute("data-tone")).toBe("bad");
  await act(async () => publishBadge({ overdue: 0, to_call: 2 }));
  expect(link.getAttribute("aria-label")).toBe("Leads, 2 to call");
  await act(async () => publishBadge({ overdue: 0, to_call: 0 }));
  expect(link.getAttribute("aria-label")).toBe("Leads");
  expect(link.querySelector("[data-tone]")).toBeNull();
});
