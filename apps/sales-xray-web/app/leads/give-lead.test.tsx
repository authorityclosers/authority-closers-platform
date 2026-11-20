import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ reassign: vi.fn() }));

vi.mock("./leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./leads-client")>()),
  reassign: calls.reassign,
}));

import { GiveLead } from "./give-lead";
import { LeadsError, type LeadDetail } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// A seller gives their lead to a colleague, always with a reason (owner, Wise
// Life, 19 Nov 2026). Made-up people only.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  calls.reassign.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const ANIKA = "aaaaaaaa-0000-4000-8000-000000000001";
const detail = (extra: Partial<LeadDetail> = {}) =>
  ({
    lead: {
      lead_id: "11111111-1111-4111-8111-111111111111",
      revision: 4,
      name: "Rohan Fictional",
      owner_person_id: "bbbbbbbb-0000-4000-8000-000000000002",
      owner_name: "Mira Sample",
    },
    can_assign: false,
    can_give: true,
    reps: [
      {
        person_id: ANIKA,
        name: "anika sample",
        open_leads: 3,
        available: true,
      },
    ],
    ...extra,
  }) as unknown as LeadDetail;

const button = (text: string) =>
  [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  ) as HTMLButtonElement | undefined;

async function click(text: string) {
  const found = button(text);
  expect(found, text).toBeTruthy();
  await act(async () => found!.click());
}

it("shows nothing unless the server lets this seller give the lead", async () => {
  await act(async () =>
    root.render(
      <GiveLead detail={detail({ can_give: false })} onGiven={vi.fn()} />,
    ),
  );
  expect(button("Give to a colleague")).toBeUndefined();
  await act(async () =>
    root.render(<GiveLead detail={detail({ reps: [] })} onGiven={vi.fn()} />),
  );
  expect(button("Give to a colleague")).toBeUndefined();
});

it("asks who, then why, and sends the reason with the move", async () => {
  const moved = detail({ can_give: false });
  calls.reassign.mockResolvedValue(moved);
  const onGiven = vi.fn();
  await act(async () =>
    root.render(<GiveLead detail={detail()} onGiven={onGiven} />),
  );
  await click("Give to a colleague");
  await click("Anika Sample");
  // No reason yet: nothing to send.
  expect(button("Give lead")?.disabled).toBe(true);
  await click("Other");
  // "Other" needs a few words.
  expect(button("Give lead")?.disabled).toBe(true);
  const note = document.querySelector("textarea") as HTMLTextAreaElement;
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!;
    set.call(note, "Customer asked for a senior");
    note.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(button("Give lead")?.disabled).toBe(false);
  await click("Give lead");
  expect(calls.reassign).toHaveBeenCalledTimes(1);
  const [lead, person, command, why] = calls.reassign.mock.calls[0];
  expect(lead.lead_id).toBe("11111111-1111-4111-8111-111111111111");
  expect(person).toBe(ANIKA);
  expect(command).toBeUndefined();
  expect(why).toEqual({ reason: "other", note: "Customer asked for a senior" });
  expect(onGiven).toHaveBeenCalledWith(moved);
});

it("keeps the sheet open and says why when the server refuses", async () => {
  calls.reassign.mockRejectedValue(
    new LeadsError(
      "Only owners and admins move leads between people here.",
      403,
    ),
  );
  const onGiven = vi.fn();
  await act(async () =>
    root.render(<GiveLead detail={detail()} onGiven={onGiven} />),
  );
  await click("Give to a colleague");
  await click("Anika Sample");
  await click("Escalation");
  await click("Give lead");
  expect(onGiven).not.toHaveBeenCalled();
  expect(button("Give lead")).toBeTruthy();
});
