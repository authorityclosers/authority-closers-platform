import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Team } from "./leads-client";
import { TakingSwitch } from "./taking-switch";
import { WorkHoursPanel } from "./team-view";

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

const team = (work_hours: Team["settings"]["work_hours"]): Team => ({
  reps: [],
  settings: {
    revision: 4,
    auto_reassign: false,
    reassign_minutes: 10,
    default_country: "91",
    work_hours,
  },
  by_stage: {},
  by_source: {},
  unassigned: 0,
  waiting_first_call: 0,
});

const button = (label: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent === label,
  )!;

it("sets the team's work days and hours, India time", async () => {
  const fetchMock = vi.fn<typeof fetch>(
    async () => new Response(JSON.stringify(team(null))),
  );
  vi.stubGlobal("fetch", fetchMock);
  const onSaved = vi.fn();
  await act(async () =>
    root.render(<WorkHoursPanel team={team(null)} onSaved={onSaved} />),
  );
  expect(host.textContent).toContain("not set");
  expect(host.textContent).toContain("never logged");
  // Monday to Saturday are picked; Sunday is added.
  expect(button("Sun").getAttribute("aria-pressed")).toBe("false");
  await act(async () => button("Sun").click());
  await act(async () => button("Save work hours").click());
  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toMatch(/\/work-hours$/);
  expect(init?.method).toBe("PUT");
  expect(JSON.parse(init?.body as string)).toEqual({
    expected_revision: 4,
    days: [0, 1, 2, 3, 4, 5, 6],
    start: "09:30",
    end: "19:00",
    pause_leads: true,
  });
  expect(onSaved).toHaveBeenCalledTimes(1);
});

it("clears the hours, and refuses hours that end before they start", async () => {
  const fetchMock = vi.fn<typeof fetch>(
    async () => new Response(JSON.stringify(team(null))),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () =>
    root.render(
      <WorkHoursPanel
        team={team({
          days: [0, 1, 2, 3, 4],
          start: "20:00",
          end: "09:00",
          pause_leads: false,
          inside: false,
          next_start: null,
        })}
        onSaved={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("after hours now");
  await act(async () => button("Save work hours").click());
  expect(fetchMock).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Work ends after it starts.");
  await act(async () => button("Clear").click());
  expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toMatchObject({
    days: [],
  });
});

it("tells the seller when new leads wait for work hours", async () => {
  await act(async () =>
    root.render(
      <TakingSwitch
        initial
        place="row"
        pausedUntil={new Date(Date.now() + 3_600_000).toISOString()}
      />,
    ),
  );
  expect(host.textContent).toContain(
    "Outside work hours. New leads wait until",
  );
});
