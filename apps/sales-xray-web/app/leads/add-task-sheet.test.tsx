// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  search: vi.fn(),
  add: vi.fn(),
  own: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../notice-center", () => ({ notify: calls.notify }));
vi.mock("./leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./leads-client")>()),
  searchDesk: calls.search,
  addTask: calls.add,
  addOwnTask: calls.own,
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { WorkspaceAccessProvider } from "../workspace-access";
import { AddTaskSheet, EARLY_MINUTES } from "./add-task-sheet";
import { LeadsError } from "./leads-client";
import { bucketFor } from "./task-words";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner order, 30 Oct 2026 (fix 4): the + sheet's Add task opened nothing.
const NOW = new Date(2026, 9, 30, 11, 0);
const TOMORROW_10 = new Date(2026, 9, 31, 10, 0);

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  calls.search.mockResolvedValue({
    leads: [
      {
        lead_id: "lead-1",
        name: "asha fictional",
        stage_label: "New",
        phone_last4: "4321",
      },
    ],
    notes: [],
    tasks: [],
  });
  calls.add.mockResolvedValue({});
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.clearAllMocks();
  localStorage.clear();
});

async function open(me: string | null = null) {
  const onAdded = vi.fn();
  const sheet = (
    <AddTaskSheet open onClose={() => {}} onAdded={onAdded} now={() => NOW} />
  );
  await act(async () =>
    root.render(
      me ? (
        <WorkspaceAccessProvider
          value={{
            status: "ready",
            authenticated: true,
            context: { personId: me, sessionId: "s", tenantId: "t" },
            retry: () => {},
          }}
        >
          {sheet}
        </WorkspaceAccessProvider>
      ) : (
        sheet
      ),
    ),
  );
  // Taps right after opening are the opening tap's echo; wait them out.
  await new Promise((resolve) => setTimeout(resolve, 400));
  return onAdded;
}

const button = (text: string) =>
  [...host.querySelectorAll("button")].find(
    (item) =>
      item.textContent?.trim() === text ||
      item.getAttribute("aria-label") === text,
  );

/** Sets a controlled input's value the way typing does. */
function type(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

async function pickLead() {
  await act(async () => {
    type(host.querySelector<HTMLInputElement>('input[type="search"]')!, "asha");
    await new Promise((resolve) => setTimeout(resolve, 300));
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  expect(calls.search).toHaveBeenCalledWith("asha", expect.anything());
  const row = [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes("Asha Fictional"),
  );
  await act(async () => row!.click());
}

it("adds a task for the picked lead at the picked time, reminding early", async () => {
  const onAdded = await open();
  // The lead is optional: Add is ready from the start.
  expect(button("Add task")?.disabled).toBe(false);
  await act(async () =>
    type(
      host.querySelector<HTMLInputElement>('input[type="text"]')!,
      "Call about the site visit",
    ),
  );
  await pickLead();
  expect(host.textContent).toContain("Asha Fictional");
  await act(async () => button("Tomorrow 10 AM")!.click());
  await act(async () => button("Add task")!.click());
  expect(calls.add).toHaveBeenCalledWith(
    "lead-1",
    {
      kind: "whatsapp",
      starts_at: TOMORROW_10.toISOString(),
      title: "Call about the site visit",
      remind_before_minutes: EARLY_MINUTES,
    },
    expect.any(String),
  );
  expect(onAdded).toHaveBeenCalledWith(TOMORROW_10);
  expect(calls.notify.mock.calls.at(-1)?.[0].tone).toBe("success");
});

it("reminds at its time with early off, and a task kept on the phone counts as added", async () => {
  calls.add.mockRejectedValue(new LeadsError("Kept on this phone.", 0, true));
  const onAdded = await open();
  await pickLead();
  await act(async () => button("Meeting")!.click());
  await act(async () => {
    host.querySelector<HTMLInputElement>('input[role="switch"]')!.click();
  });
  await act(async () => button("Add task")!.click());
  expect(calls.add.mock.calls[0][1]).toMatchObject({
    kind: "meeting",
    remind_before_minutes: 0,
    title: null,
  });
  expect(onAdded).toHaveBeenCalledTimes(1);
  expect(calls.notify.mock.calls.at(-1)?.[0].tone).toBe("info");
});

it("keeps the form open with a corner card when the task isn't added", async () => {
  calls.add.mockRejectedValue(new LeadsError("No lead here.", 404));
  const onAdded = await open();
  await pickLead();
  await act(async () => button("Add task")!.click());
  expect(onAdded).not.toHaveBeenCalled();
  expect(calls.notify.mock.calls.at(-1)?.[0]).toMatchObject({
    tone: "error",
    title: "The task wasn't added",
    message: "No lead here.",
  });
});

it("sorts a new task into Overdue, Today or Upcoming as the server does", () => {
  expect(bucketFor(new Date(2026, 9, 30, 9, 0), NOW)).toBe("overdue");
  expect(bucketFor(new Date(2026, 9, 30, 18, 0), NOW)).toBe("today");
  expect(bucketFor(TOMORROW_10, NOW)).toBe("upcoming");
});

// A task is on the lead owner's list (lead_desk/tasks.py): on a teammate's
// lead the form and the saved card say whose it is, so an owner doesn't look
// for it in their own Tasks.
it("says a task on a teammate's lead goes on their list", async () => {
  calls.search.mockResolvedValue({
    leads: [
      {
        lead_id: "lead-2",
        name: "asha fictional",
        stage_label: "New",
        phone_last4: "4321",
        owner_person_id: "seller-2",
        owner_name: "ravi sample",
      },
    ],
    notes: [],
    tasks: [],
  });
  await open("me");
  await pickLead();
  expect(host.textContent).toContain(
    "Ravi Sample's lead: the task goes on their list and reminds them.",
  );
  await act(async () => button("Add task")!.click());
  expect(calls.notify.mock.calls.at(-1)?.[0].message).toBe(
    "Asha Fictional · on Ravi Sample's list",
  );
});

// The owner's spec (30 Oct 2026): "optional linked lead". With none, the task
// is your own and goes on your list (migration 0147).
it("adds a task of your own when no lead is picked", async () => {
  calls.own.mockResolvedValue({});
  const onAdded = await open();
  await act(async () =>
    type(
      host.querySelector<HTMLInputElement>('input[type="text"]')!,
      "Renew the brochure print order",
    ),
  );
  await act(async () => button("Other")!.click());
  await act(async () => button("Add task")!.click());
  expect(calls.add).not.toHaveBeenCalled();
  expect(calls.own).toHaveBeenCalledWith(
    {
      kind: "other",
      starts_at: new Date(2026, 9, 30, 12, 0).toISOString(),
      title: "Renew the brochure print order",
      remind_before_minutes: EARLY_MINUTES,
    },
    expect.any(String),
  );
  expect(onAdded).toHaveBeenCalledTimes(1);
  expect(calls.notify.mock.calls.at(-1)?.[0]).toMatchObject({
    tone: "success",
    message: "On your list",
  });
});

// Persona QA 8417b4d1 (31 Oct 2026): tasks are the non-calling work, the
// time reads day first, tomorrow afternoon is one tap, and no helper lines.
it("offers non-calling kinds, tomorrow at 4 PM and the time day first", async () => {
  calls.own.mockResolvedValue({});
  await open();
  expect(button("Call back")).toBeUndefined();
  expect(button("WhatsApp")?.getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).not.toContain("A reminder on");
  await act(async () => button("Tomorrow 4 PM")!.click());
  expect(host.textContent).toMatch(/Tomorrow, 4:00\spm/i);
  await act(async () =>
    type(
      host.querySelector<HTMLInputElement>('input[type="datetime-local"]')!,
      "2026-11-03T16:00",
    ),
  );
  expect(host.textContent).toContain("3 Nov");
  expect(host.textContent).not.toContain("Nov 3");
  await act(async () => button("Add task")!.click());
  expect(calls.own.mock.calls[0][0]).toMatchObject({
    kind: "whatsapp",
    starts_at: new Date(2026, 10, 3, 16, 0).toISOString(),
  });
});

// The test robot, 1 Nov 2026 (2e72e8fa, 11ef4f38, 0f5c0fb1): Back, Forward or a
// refresh lost a half-typed task. Its title is kept as a draft until saved.
it("keeps a half-typed task title until it is saved", async () => {
  calls.own.mockResolvedValue({});
  await open();
  const title = () =>
    host.querySelector<HTMLInputElement>(
      'input[placeholder="Send the brochure"]',
    )!;
  await act(async () => type(title(), "Send the fee sheet"));
  await act(async () => root.unmount());
  root = createRoot(host);
  const onAdded = await open();
  expect(title().value).toBe("Send the fee sheet");
  await act(async () => button("Add task")!.click());
  for (let i = 0; i < 6; i++) await act(async () => Promise.resolve());
  expect(onAdded).toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
});
