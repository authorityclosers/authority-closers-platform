import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { History } from "./lead-sheet";
import type { LeadEvent } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

const call = (extra: Partial<LeadEvent>): LeadEvent => ({
  kind: "call",
  at: "2026-10-18T05:30:00Z",
  actor_name: "Asha",
  stage: null,
  stage_label: null,
  reason: null,
  reason_label: null,
  connected: true,
  note: null,
  next_action_at: null,
  owner_name: null,
  previous_owner_name: null,
  allocation_reason: null,
  source_label: null,
  submission_id: null,
  simulated: null,
  duration_seconds: 300,
  via: "phone",
  direction: "outgoing",
  event_id: "22222222-2222-4222-8222-222222222222",
  can_hide: true,
  private: false,
  ...extra,
});

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

it("lets the seller make their own phone call private", async () => {
  const fetchMock = vi.fn<typeof fetch>(
    async () => new Response(JSON.stringify({ events: [] })),
  );
  vi.stubGlobal("fetch", fetchMock);
  const onChanged = vi.fn();
  await act(async () =>
    root.render(<History events={[call({})]} onChanged={onChanged} />),
  );
  const button = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Make private",
  )!;
  await act(async () => button.click());
  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toMatch(
    /\/calls\/22222222-2222-4222-8222-222222222222\/private$/,
  );
  expect(JSON.parse(init?.body as string)).toMatchObject({ private: true });
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("marks a private call, and offers to show it again", async () => {
  await act(async () =>
    root.render(
      <History
        events={[call({ private: true })]}
        onChanged={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("Private");
  expect(host.textContent).toContain("Only you see this call.");
  expect(host.textContent).toContain("Show to my team");
});

it("offers nothing on someone else's call", async () => {
  await act(async () =>
    root.render(
      <History events={[call({ can_hide: false })]} onChanged={() => {}} />,
    ),
  );
  expect(host.querySelector("button")).toBeNull();
});
