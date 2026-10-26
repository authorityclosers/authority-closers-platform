import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ reassign: vi.fn(), haptic: vi.fn() }));

vi.mock("../ui/haptics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../ui/haptics")>()),
  haptic: calls.haptic,
}));
vi.mock("./leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./leads-client")>()),
  reassign: calls.reassign,
}));

import { LeadsError, type LeadDetail } from "./leads-client";
import { ReassignSheet } from "./reassign-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Reassign (owner, #33, 26 Oct 2026): its own sheet with search, photos or
// characters, the person who has the lead ticked, and a haptic on the pick.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  calls.reassign.mockReset();
  calls.haptic.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  // The characters list: none shipped here, so avatars keep their initials.
  vi.stubGlobal("fetch", async () => Response.json({ characters: [] }));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const ASHA = "aaaaaaaa-0000-4000-8000-000000000001";
const MEERA = "bbbbbbbb-0000-4000-8000-000000000002";
const rep = (person_id: string, name: string, open_leads = 3) => ({
  person_id,
  name,
  open_leads,
  available: true,
});

const detail = {
  lead: {
    lead_id: "11111111-1111-4111-8111-111111111111",
    revision: 3,
    name: "Ravi Kulkarni",
    owner_person_id: ASHA,
    owner_name: "Asha Fictional",
  },
  reps: [
    rep("cccccccc-0000-4000-8000-000000000003", "Dev Fictional"),
    rep(ASHA, "Asha Fictional", 7),
    rep(MEERA, "Meera Fictional", 1),
    rep("dddddddd-0000-4000-8000-000000000004", "Kiran Fictional"),
    rep("eeeeeeee-0000-4000-8000-000000000005", "Sam Fictional"),
  ],
} as unknown as LeadDetail;

async function open(handlers: { onMoved?: () => void; onClose?: () => void }) {
  await act(async () =>
    root.render(
      <ReassignSheet
        open
        detail={detail}
        onClose={handlers.onClose ?? (() => undefined)}
        onMoved={handlers.onMoved ?? (() => undefined)}
      />,
    ),
  );
}

const people = () => [
  ...document.querySelectorAll<HTMLButtonElement>(
    '[aria-label="People"] button',
  ),
];

it("lists the owner first, ticked, and finds people by name", async () => {
  await open({});
  const rows = people();
  expect(rows[0].textContent).toContain("Asha Fictional");
  expect(rows[0].textContent).toContain("Has this lead now");
  expect(rows[0].getAttribute("aria-current")).toBe("true");
  expect(rows[0].disabled).toBe(true);
  expect(rows[0].querySelector('[aria-label="Current owner"]')).not.toBeNull();
  expect(rows).toHaveLength(5);

  const find = document.querySelector<HTMLInputElement>(
    'input[aria-label="Find a person"]',
  )!;
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    set.call(find, "mee");
    find.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(people().map((row) => row.textContent)).toEqual([
    "MFMeera Fictional1 open lead",
  ]);
});

it("moves the lead on a tap, felt in the hand, and closes", async () => {
  const moved = vi.fn();
  const closed = vi.fn();
  calls.reassign.mockResolvedValue({ lead: { lead_id: "x" } });
  await open({ onMoved: moved, onClose: closed });
  const meera = people().find((row) => row.textContent?.includes("Meera"))!;
  await act(async () => meera.click());
  expect(calls.reassign).toHaveBeenCalledWith(detail.lead, MEERA);
  expect(calls.haptic.mock.calls).toEqual([["tap"], ["success"]]);
  expect(moved).toHaveBeenCalledWith({ lead: { lead_id: "x" } });
  expect(closed).toHaveBeenCalledOnce();
});

it("lets the lead rules pick, and says when a move fails", async () => {
  calls.reassign.mockRejectedValue(
    new LeadsError("Someone moved it first.", 409),
  );
  const closed = vi.fn();
  await open({ onClose: closed });
  const rules = [...document.querySelectorAll("button")].find((button) =>
    button.textContent?.startsWith("Let the lead rules pick"),
  )!;
  await act(async () => rules.click());
  expect(calls.reassign).toHaveBeenCalledWith(detail.lead, null);
  expect(calls.haptic.mock.calls).toEqual([["tap"], ["error"]]);
  expect(document.querySelector('[role="alert"]')?.textContent).toBe(
    "Someone moved it first.",
  );
  expect(closed).not.toHaveBeenCalled();
});
