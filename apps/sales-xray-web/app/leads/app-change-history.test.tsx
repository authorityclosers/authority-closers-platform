// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: unknown; href: string }) => (
    <a href={href}>{children as never}</a>
  ),
}));

import { History } from "./lead-sheet";
import type { LeadDetail, LeadEvent } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// AI writes (owner order, 25 Oct 2026): a note an AI app added says which app, and
// whoever may undo it sees Undo for 7 days.
const LEAD = "11111111-1111-4111-8111-111111111111";

const note = (extra: Partial<LeadEvent>): LeadEvent =>
  ({
    kind: "note",
    at: "2026-10-25T07:00:00Z",
    actor_name: "Rahul Example",
    stage: null,
    stage_label: null,
    reason: null,
    reason_label: null,
    connected: null,
    note: "Wants a demo on Monday",
    next_action_at: null,
    owner_name: null,
    previous_owner_name: null,
    allocation_reason: null,
    source_label: null,
    submission_id: null,
    simulated: null,
    duration_seconds: null,
    ...extra,
  }) as LeadEvent;

let host: HTMLDivElement;
let root: Root;
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

it("shows which app added a note, and Undo reads the lead again", async () => {
  const calls: { url: string; method: string }[] = [];
  const after = { events: [] } as unknown as LeadDetail;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method ?? "GET" });
      return Response.json(
        String(url).endsWith("/undo") ? { status: "undone" } : after,
      );
    }),
  );
  const changed = vi.fn();
  await act(async () =>
    root.render(
      <History
        events={[
          note({ app_label: "ChatGPT", change_id: "c1", can_undo: true }),
        ]}
        onChanged={changed}
        leadId={LEAD}
      />,
    ),
  );
  expect(host.textContent).toContain("via ChatGPT");
  const undo = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Undo",
  )!;
  await act(async () => undo.click());
  await act(async () => new Promise((done) => setTimeout(done, 0)));
  expect(calls[0]).toEqual({
    url: "/v1/lead-desk/ai-changes/c1/undo",
    method: "POST",
  });
  expect(calls[1].url).toContain(`/v1/lead-desk/leads/${LEAD}`);
  expect(changed).toHaveBeenCalledWith(after);
});

it("has no Undo once it may not be undone, or without the lead", async () => {
  await act(async () =>
    root.render(
      <History
        events={[
          note({ app_label: "Claude", change_id: "c2", can_undo: false }),
          note({ app_label: "ChatGPT", change_id: "c3", can_undo: true }),
        ]}
        onChanged={vi.fn()}
      />,
    ),
  );
  expect(host.textContent).toContain("via Claude");
  expect(
    [...host.querySelectorAll("button")].some(
      (button) => button.textContent === "Undo",
    ),
  ).toBe(false);
});
