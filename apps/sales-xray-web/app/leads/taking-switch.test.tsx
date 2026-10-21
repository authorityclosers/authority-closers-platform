import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TakingSwitch } from "./taking-switch";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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
  vi.unstubAllGlobals();
});

const toggle = () =>
  host.querySelector<HTMLButtonElement>('button[role="switch"]')!;

it("turns new leads off for the seller and says what that means", async () => {
  const fetchMock = vi.fn<typeof fetch>(
    async () =>
      new Response(
        JSON.stringify({
          person_id: "p",
          name: "Asha",
          role: "member",
          can_manage: false,
          taking_leads: false,
        }),
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const onChanged = vi.fn();
  await act(async () =>
    root.render(<TakingSwitch initial place="row" onChanged={onChanged} />),
  );
  expect(toggle().getAttribute("aria-checked")).toBe("true");
  expect(host.textContent).toContain("Taking new leads");

  await act(async () => toggle().click());
  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toMatch(/\/me\/taking$/);
  expect(init?.method).toBe("PUT");
  expect(JSON.parse(init?.body as string)).toEqual({ taking: false });
  expect(toggle().getAttribute("aria-checked")).toBe("false");
  expect(host.textContent).toContain("Not taking new leads");
  expect(host.textContent).toContain("Your open leads stay with you");
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("puts the switch back when saving fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ detail: "Try again." }), {
          status: 500,
        }),
    ),
  );
  await act(async () => root.render(<TakingSwitch initial place="header" />));
  await act(async () => toggle().click());
  expect(toggle().getAttribute("aria-checked")).toBe("true");
  expect(host.querySelector('[role="alert"]')?.textContent).toBe("Try again.");
});

// Owner, 22 Oct 2026: wide switch rows "waste space once ticked".
it("is a small chip on Leads that flips in one tap", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(
      async () =>
        new Response(
          JSON.stringify({
            person_id: "p",
            name: "Asha",
            role: "member",
            can_manage: false,
            taking_leads: false,
          }),
        ),
    ),
  );
  await act(async () => root.render(<TakingSwitch initial place="chip" />));
  expect(toggle().getAttribute("aria-checked")).toBe("true");
  expect(toggle().textContent).toBe("Taking leads");
  await act(async () => toggle().click());
  expect(toggle().getAttribute("aria-checked")).toBe("false");
  expect(toggle().textContent).toBe("Not taking leads");
});
