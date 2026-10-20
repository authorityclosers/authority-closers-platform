// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  send: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: calls.refresh }),
}));
vi.mock("../lib/client-api", () => ({ send: calls.send }));

import { LeadAiRaise } from "./lead-ai-raise";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("raises to the next preset with the revision read, then reads the page again", async () => {
  calls.send.mockResolvedValueOnce({ ok: true, status: 200, data: {} });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(<LeadAiRaise revision={3} raiseTo={300} atCap waiting={4} />),
  );
  expect(host.textContent).toContain(
    "Cap reached: automatic replies are waiting",
  );
  const button = host.querySelector("button")!;
  expect(button.textContent).toBe("Raise to ₹300 and resume");
  await act(async () => button.click());
  expect(calls.send).toHaveBeenCalledWith(
    "POST",
    "/v1/admin/lead-desk-ai/raise",
    { expected_revision: 3 },
    null,
  );
  expect(calls.refresh).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="status"]')?.textContent).toBe(
    "Raised to ₹300; replies resume",
  );

  // Someone saved first: the Lead Desk's words, and nothing read again.
  calls.send.mockResolvedValueOnce({
    ok: false,
    status: 409,
    message: "Someone saved first.",
  });
  await act(async () => button.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "Someone saved first.",
  );
  expect(calls.refresh).toHaveBeenCalledOnce();
  await act(async () => root.unmount());
  host.remove();
});
