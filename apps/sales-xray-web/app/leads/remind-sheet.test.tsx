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
  expect(button("Tomorrow 10 AM")?.getAttribute("aria-pressed")).toBe("true");
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
  await click("This evening");
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
  expect(new Date(body.starts_at).getHours()).toBe(18);
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
