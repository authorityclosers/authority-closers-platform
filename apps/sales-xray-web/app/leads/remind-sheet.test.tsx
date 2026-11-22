// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ add: vi.fn(), notify: vi.fn() }));

vi.mock("../notice-center", () => ({ notify: calls.notify }));
vi.mock("./leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./leads-client")>()),
  addTask: calls.add,
}));

import { LeadsError } from "./leads-client";
import { RemindSheet } from "./remind-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date(2026, 9, 24, 11, 0);

let container: HTMLDivElement;
let root: Root;
const saved: unknown[] = [];

async function show() {
  await act(async () => {
    root.render(
      <RemindSheet
        open
        leadId="lead-1"
        leadName="Asha Fictional"
        onClose={() => undefined}
        onSaved={(task) => saved.push(task)}
        now={() => NOW}
      />,
    );
  });
}

const button = (label: string) =>
  [...container.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );

const click = async (label: string) => {
  await act(async () => {
    button(label)?.click();
  });
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  saved.length = 0;
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

it("saves a call back for tomorrow at 10 in two taps", async () => {
  calls.add.mockResolvedValue({ task_id: "t1" });
  await show();
  expect(button("Call back")?.getAttribute("aria-pressed")).toBe("true");
  expect(button("Tomorrow morning")?.getAttribute("aria-pressed")).toBe("true");
  // The exact time it reminds, in words.
  expect(container.textContent).toMatch(/Reminds you Tomorrow 10:00\sam/);
  await click("Save");
  const [leadId, body, command] = calls.add.mock.calls[0];
  expect(leadId).toBe("lead-1");
  expect(body.kind).toBe("call_back");
  expect(new Date(body.starts_at).getTime()).toBe(
    new Date(2026, 9, 25, 10, 0).getTime(),
  );
  expect(body.ends_at).toBeNull();
  expect(typeof command).toBe("string");
  expect(saved).toEqual([{ task_id: "t1" }]);
});

it("asks where for a meeting and books an hour", async () => {
  calls.add.mockResolvedValue({ task_id: "t2" });
  await show();
  await click("Meeting");
  await click("In 1 hour");
  const where = container.querySelector<HTMLInputElement>(
    "input[placeholder^='Office']",
  );
  expect(where).not.toBeNull();
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    set?.call(where, "Baner office");
    where?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Save");
  const [, body] = calls.add.mock.calls[0];
  expect(body.kind).toBe("meeting");
  expect(body.location).toBe("Baner office");
  expect(
    new Date(body.ends_at).getTime() - new Date(body.starts_at).getTime(),
  ).toBe(60 * 60_000);
  expect(new Date(body.starts_at).getTime()).toBe(NOW.getTime() + 60 * 60_000);
});

// Owner, 22 Nov 2026: "quick presets of 1 min, 2 min, 5 min, 15 min, 30 min,
// 1 h, tomorrow morning, not just 1 hour", each saying the exact time.
it.each([
  ["In 1 min", 1, "11:01"],
  ["In 2 min", 2, "11:02"],
  ["In 5 min", 5, "11:05"],
  ["In 15 min", 15, "11:15"],
  ["In 30 min", 30, "11:30"],
  ["In 1 hour", 60, "12:00"],
])("%s reminds that many minutes from Save", async (label, minutes, clock) => {
  calls.add.mockResolvedValue({ task_id: "t" });
  await show();
  await click(label);
  expect(button(label)?.getAttribute("aria-pressed")).toBe("true");
  expect(container.textContent).toContain(`Reminds you Today ${clock}`);
  await click("Save");
  const [, body] = calls.add.mock.calls[0];
  expect(new Date(body.starts_at).getTime()).toBe(
    NOW.getTime() + minutes * 60_000,
  );
});

it("picks any date and time with the phone's own date and time fields", async () => {
  calls.add.mockResolvedValue({ task_id: "t" });
  await show();
  await click("Pick date & time");
  const date = container.querySelector<HTMLInputElement>('input[type="date"]')!;
  const time = container.querySelector<HTMLInputElement>('input[type="time"]')!;
  // It opens on the time shown (Tomorrow morning).
  expect(date.value).toBe("2026-10-25");
  const type = async (input: HTMLInputElement, value: string) =>
    act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set?.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  await type(date, "2026-10-27");
  await type(
    container.querySelector<HTMLInputElement>('input[type="time"]')!,
    "16:45",
  );
  expect(time).not.toBeNull();
  expect(container.textContent).toMatch(/Reminds you Tue 27 Oct, 4:45\spm/);
  await click("Save");
  const [, body] = calls.add.mock.calls[0];
  expect(new Date(body.starts_at).getTime()).toBe(
    new Date(2026, 9, 27, 16, 45).getTime(),
  );
});

it("says a picked time that has passed, and does not save it", async () => {
  await show();
  await click("Pick date & time");
  for (const [kind, value] of [
    ["date", "2026-10-24"],
    ["time", "09:00"],
  ]) {
    await act(async () => {
      const input = container.querySelector<HTMLInputElement>(
        `input[type="${kind}"]`,
      )!;
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set?.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  expect(container.textContent).toContain("That time has passed.");
  expect(button("Save")?.hasAttribute("disabled")).toBe(true);
});

it("makes Tomorrow morning the team's opening, in the team's clock", async () => {
  calls.add.mockResolvedValue({ task_id: "t" });
  await act(async () => {
    root.render(
      <RemindSheet
        open
        leadId="lead-1"
        leadName="Asha Fictional"
        onClose={() => undefined}
        onSaved={(task) => saved.push(task)}
        hours={{
          days: [0, 1, 2, 3, 4, 5],
          start: "09:30",
          timezone: "Asia/Kolkata",
        }}
        now={() => new Date("2026-11-22T20:40:00+05:30")}
      />,
    );
  });
  await click("Save");
  const [, body] = calls.add.mock.calls[0];
  expect(new Date(body.starts_at).toISOString()).toBe(
    new Date("2026-11-23T09:30:00+05:30").toISOString(),
  );
});

it("uses the same command for a second Save after a failure", async () => {
  calls.add.mockRejectedValueOnce(new LeadsError("Try again.", 503));
  calls.add.mockResolvedValueOnce({ task_id: "t3" });
  await show();
  await click("Save");
  expect(container.textContent).toContain("Try again.");
  await click("Save");
  expect(calls.add.mock.calls[1][2]).toBe(calls.add.mock.calls[0][2]);
  expect(saved).toEqual([{ task_id: "t3" }]);
});

it("counts a reminder the phone kept as saved", async () => {
  calls.add.mockRejectedValue(new LeadsError("Kept on this phone.", 0, true));
  await show();
  await click("Save");
  expect(saved).toEqual([null]);
  expect(calls.notify.mock.calls[0][0].tone).toBe("info");
});

// The robot, 9 Nov 2026 (karan at 360): 40 characters in "Follow-up" were gone
// after a refresh. Kept for the lead through a refresh and Back; Cancel drops.
it("keeps what was written through a refresh and Back, and drops it on Cancel", async () => {
  localStorage.clear();
  const words = "QA draft 1 — Rahul ko kal call karna hai";
  const note = () => container.querySelector("textarea")!;
  await show();
  await click("Meeting");
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(note(), words);
    note().dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(localStorage.getItem("sx-draft:remind:lead-1")).toContain(words);

  // A refresh: the page starts again, and the sheet shows what was written.
  act(() => root.unmount());
  root = createRoot(container);
  await show();
  expect(note().value).toBe(words);
  expect(button("Meeting")?.getAttribute("aria-pressed")).toBe("true");

  // Back closes it and keeps the words.
  await act(async () => Promise.resolve());
  await act(async () => window.history.back());
  await act(async () => Promise.resolve());
  expect(localStorage.getItem("sx-draft:remind:lead-1")).toContain(words);

  // Cancel drops them.
  await click("Cancel");
  expect(localStorage.getItem("sx-draft:remind:lead-1")).toBeNull();
  expect(note().value).toBe("");
});
