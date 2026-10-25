// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  read: vi.fn(),
  action: vi.fn(),
  snooze: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../notice-center", () => ({ notify: calls.notify }));
vi.mock("./leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./leads-client")>()),
  readTasks: calls.read,
  taskAction: calls.action,
  snoozeTask: calls.snooze,
}));

import { LeadsError, type TaskList, type TaskView } from "./leads-client";
import { TasksView } from "./tasks-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date(2026, 9, 24, 11, 0);

const task = (id: string, extra: Partial<TaskView> = {}): TaskView => ({
  task_id: id,
  lead_id: `lead-${id}`,
  lead_name: "asha fictional",
  kind: "call_back",
  title: "Call back Asha Fictional",
  note: null,
  starts_at: new Date(2026, 9, 24, 17, 30).toISOString(),
  ends_at: null,
  location: null,
  status: "open",
  done_at: null,
  original_due_at: new Date(2026, 9, 24, 17, 30).toISOString(),
  snoozes: 0,
  rollovers: 0,
  source: "seller",
  revision: 1,
  owner_person_id: "me",
  overdue: false,
  bucket: "today",
  ...extra,
});

const LIST: TaskList = {
  tasks: [
    task("t1", { note: "Asked for the 2 BHK brochure" }),
    task("t2", {
      kind: "meeting",
      title: "Meeting with Ravi Sample",
      lead_name: "ravi sample",
      location: "Baner office",
    }),
  ],
  counts: { overdue: 2, today: 2, upcoming: 5 },
};

let container: HTMLDivElement;
let root: Root;
const opened: string[] = [];

async function show() {
  await act(async () => {
    root.render(
      <TasksView onOpen={(leadId) => opened.push(leadId)} now={() => NOW} />,
    );
  });
}

const button = (label: string) =>
  [...container.querySelectorAll("button")].find(
    (item) =>
      item.getAttribute("aria-label") === label ||
      item.textContent?.trim() === label,
  );

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  opened.length = 0;
  calls.read.mockResolvedValue(LIST);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

it("lists today's tasks with what, for whom, where and when, and counts each list", async () => {
  await show();
  expect(calls.read).toHaveBeenCalledWith("today", expect.anything());
  const text = container.textContent ?? "";
  expect(text).toContain("Overdue 2");
  expect(text).toContain("Today 2");
  expect(text).toContain("Upcoming 5");
  expect(text).toContain("Call back Asha Fictional");
  expect(text).toContain("Asked for the 2 BHK brochure");
  expect(text).toContain("Baner office");
  expect(text).toContain("Meeting · Ravi Sample");
});

it("opens the lead on a tap", async () => {
  await show();
  await act(async () => {
    container.querySelector<HTMLButtonElement>("[data-lead-row]")?.click();
  });
  expect(opened).toEqual(["lead-t1"]);
});

it("takes a task off on Done and offers Undo", async () => {
  calls.action.mockResolvedValue(task("t1", { status: "done", revision: 2 }));
  await show();
  await act(async () => {
    button("Done: Call back Asha Fictional")?.click();
  });
  expect(calls.action).toHaveBeenCalledWith(
    expect.objectContaining({ task_id: "t1", revision: 1 }),
    "done",
  );
  expect(container.textContent).not.toContain("Asked for the 2 BHK brochure");
  const notice = calls.notify.mock.calls.at(-1)?.[0];
  expect(notice.title).toBe("Done: Call back Asha Fictional");
  expect(notice.action.label).toBe("Undo");
  calls.action.mockResolvedValue(task("t1", { revision: 3 }));
  await act(async () => notice.action.run());
  expect(calls.action).toHaveBeenLastCalledWith(
    expect.objectContaining({ task_id: "t1", revision: 2 }),
    "undo",
  );
});

it("counts a Done the phone kept as done", async () => {
  calls.action.mockRejectedValue(
    new LeadsError("Kept on this phone.", 0, true),
  );
  await show();
  await act(async () => {
    button("Done: Call back Asha Fictional")?.click();
  });
  expect(container.textContent).not.toContain("Asked for the 2 BHK brochure");
  expect(calls.notify.mock.calls.at(-1)?.[0].tone).toBe("info");
});

it("puts a task back and says why when Done fails", async () => {
  calls.action.mockRejectedValue(new LeadsError("This task changed.", 409));
  await show();
  await act(async () => {
    button("Done: Call back Asha Fictional")?.click();
  });
  expect(container.textContent).toContain("Asked for the 2 BHK brochure");
  const notice = calls.notify.mock.calls.at(-1)?.[0];
  expect([notice.tone, notice.message]).toEqual([
    "error",
    "This task changed.",
  ]);
});

it("moves a task later from the sheet", async () => {
  calls.snooze.mockResolvedValue(
    task("t1", {
      starts_at: new Date(2026, 9, 24, 18, 0).toISOString(),
      revision: 2,
    }),
  );
  await show();
  await act(async () => {
    button("Later: Call back Asha Fictional")?.click();
  });
  await act(async () => {
    button("1 hour")?.click();
  });
  expect(calls.snooze).toHaveBeenCalledWith(
    expect.objectContaining({ task_id: "t1" }),
    "1h",
  );
  expect(calls.notify.mock.calls.at(-1)?.[0].title).toMatch(/^Moved to /);
});

it("says so when a list is empty", async () => {
  calls.read.mockResolvedValue({ tasks: [], counts: {} });
  await show();
  expect(container.textContent).toContain("Nothing due today");
});
