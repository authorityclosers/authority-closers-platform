import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import { HubRedirect, hubTarget } from "./hub-redirect";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 23 Oct 2026: the organisation's settings live in its hub; an old
// address (a saved link, a connect flow coming back) keeps its own query.
it("goes to the hub's tab with the old address's own query kept", () => {
  expect(hubTarget("/organisation?tab=team", "")).toBe(
    "/organisation?tab=team",
  );
  expect(
    hubTarget(
      "/organisation?tab=connections&part=apps",
      "?connected=meta&page=123",
      "#whatsapp",
    ),
  ).toBe(
    "/organisation?tab=connections&part=apps&connected=meta&page=123#whatsapp",
  );
  // The hub decides its own tab and part.
  expect(
    hubTarget("/organisation?tab=leads&part=stages", "?tab=x&part=y&q=1"),
  ).toBe("/organisation?tab=leads&part=stages&q=1");
});

// Owner, 26 Oct 2026: no bare "Opening…" line on an empty page while it goes.
it("shows the organisation's outline while it opens the hub", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(<HubRedirect to="/organisation?tab=company" />),
  );
  expect(replace).toHaveBeenCalledWith("/organisation?tab=company");
  const status = host.querySelector('[role="status"]');
  expect(status?.getAttribute("aria-busy")).toBe("true");
  expect(status?.getAttribute("aria-label")).toBe("Loading organisation");
  expect(host.textContent).not.toContain("Opening the organisation");
  await act(async () => root.unmount());
  host.remove();
});
