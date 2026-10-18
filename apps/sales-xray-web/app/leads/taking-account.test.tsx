import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useTakingLeads } from "./taking-account";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Probe({ enabled }: { enabled: boolean }) {
  const taking = useTakingLeads(enabled);
  if (!taking) return <p>none</p>;
  return (
    <button type="button" onClick={taking.toggle}>
      {taking.taking ? "on" : "off"}
      {taking.pausedUntil ? " paused" : ""}
    </button>
  );
}

const ME = {
  person_id: "p",
  name: "Asha",
  role: "member",
  can_manage: false,
  taking_leads: true,
  paused_until: null,
};

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

it("reads nothing until the account sheet is open in an organisation", async () => {
  const fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => root.render(<Probe enabled={false} />));
  expect(fetchMock).not.toHaveBeenCalled();
  expect(host.textContent).toBe("none");
});

it("switches new leads off from the account sheet", async () => {
  const fetchMock = vi.fn<typeof fetch>(async (_url, init) =>
    init?.method === "PUT"
      ? new Response(JSON.stringify({ ...ME, taking_leads: false }))
      : new Response(JSON.stringify(ME)),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => root.render(<Probe enabled />));
  expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/v1\/lead-desk\/me$/);
  expect(host.textContent).toBe("on");
  await act(async () => host.querySelector("button")!.click());
  const [url, init] = fetchMock.mock.calls[1];
  expect(String(url)).toMatch(/\/me\/taking$/);
  expect(JSON.parse(init?.body as string)).toEqual({ taking: false });
  expect(host.textContent).toBe("off");
});

it("shows no row where Leads is not available", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => new Response("{}", { status: 403 })),
  );
  await act(async () => root.render(<Probe enabled />));
  expect(host.textContent).toBe("none");
});

it("says when new leads wait for work hours", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(
      async () =>
        new Response(
          JSON.stringify({ ...ME, paused_until: "2026-10-19T04:00:00Z" }),
        ),
    ),
  );
  await act(async () => root.render(<Probe enabled />));
  expect(host.textContent).toBe("on paused");
});
