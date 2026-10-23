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
  document.querySelector<HTMLButtonElement>('button[role="switch"]')!;
const inSheet = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("dialog button")].find(
    (button) => button.textContent === name,
  )!;
const me = (taking: boolean) =>
  new Response(
    JSON.stringify({
      person_id: "p",
      name: "Asha",
      role: "member",
      can_manage: false,
      taking_leads: taking,
    }),
  );

// Owner, 23 Oct 2026: "the user must feel the importance of that, and a popup".
it("asks before stopping new leads, then says what that means", async () => {
  const fetchMock = vi.fn<typeof fetch>(async () => me(false));
  vi.stubGlobal("fetch", fetchMock);
  const onChanged = vi.fn();
  await act(async () =>
    root.render(<TakingSwitch initial place="row" onChanged={onChanged} />),
  );
  expect(toggle().getAttribute("aria-checked")).toBe("true");
  expect(host.textContent).toContain("You're receiving new leads");

  await act(async () => toggle().click());
  expect(fetchMock).not.toHaveBeenCalled();
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Your open leads and follow-ups stay with you.",
  );

  await act(async () => inSheet("Stop taking leads").click());
  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toMatch(/\/me\/taking$/);
  expect(init?.method).toBe("PUT");
  expect(JSON.parse(init?.body as string)).toEqual({ taking: false });
  expect(toggle().getAttribute("aria-checked")).toBe("false");
  expect(host.textContent).toContain("Paused: new leads go to others");
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("turns new leads back on at once, and back off again if saving fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ detail: "Try again." }), {
          status: 500,
        }),
    ),
  );
  await act(async () =>
    root.render(<TakingSwitch initial={false} place="row" />),
  );
  await act(async () => toggle().click());
  expect(document.querySelector("dialog[open]")).toBeNull();
  expect(toggle().getAttribute("aria-checked")).toBe("false");
});

// The chip on Leads opens the switch in a sheet; a stray tap stops nothing.
it("is a chip on Leads that opens the switch instead of flipping", async () => {
  const fetchMock = vi.fn<typeof fetch>(async () => me(false));
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => root.render(<TakingSwitch initial place="chip" />));
  const chip = host.querySelector<HTMLButtonElement>("button")!;
  expect(chip.textContent).toBe("Taking leads");
  await act(async () => chip.click());
  expect(fetchMock).not.toHaveBeenCalled();
  expect(toggle().getAttribute("aria-checked")).toBe("true");
  await act(async () => toggle().click());
  await act(async () => inSheet("Stop taking leads").click());
  expect(chip.textContent).toBe("Not taking leads");
});

it("lets an owner hand leads out after hours, after asking", async () => {
  const hours = {
    days: [1, 2, 3, 4, 5, 6],
    start: "09:00",
    end: "19:00",
    pause_leads: true,
    inside: false,
    next_start: null,
  };
  const team = (pause: boolean) => ({
    reps: [],
    settings: {
      revision: 4,
      auto_reassign: false,
      reassign_minutes: 15,
      default_country: "IN",
      work_hours: { ...hours, pause_leads: pause },
    },
    by_stage: {},
    by_source: {},
    unassigned: 0,
    waiting_first_call: 0,
  });
  const fetchMock = vi.fn<typeof fetch>(async (_url, init) =>
    init?.method === "PUT"
      ? new Response(JSON.stringify(team(false)))
      : new Response(JSON.stringify(team(true))),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () =>
    root.render(
      <TakingSwitch
        initial
        place="row"
        pausedUntil={new Date(Date.now() + 3_600_000).toISOString()}
      />,
    ),
  );
  expect(host.textContent).toContain("Outside work hours (09:00 to 19:00)");
  const lift = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Hand out leads after hours",
  )!;
  await act(async () => lift.click());
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await act(async () => inSheet("Hand out leads now").click());
  const [url, init] = fetchMock.mock.calls[1];
  expect(String(url)).toMatch(/\/work-hours$/);
  expect(JSON.parse(init?.body as string)).toEqual({
    expected_revision: 4,
    days: [1, 2, 3, 4, 5, 6],
    start: "09:00",
    end: "19:00",
    pause_leads: false,
  });
  expect(host.textContent).toContain("You're receiving new leads");
});
