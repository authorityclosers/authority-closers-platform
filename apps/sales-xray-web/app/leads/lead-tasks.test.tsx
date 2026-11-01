// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => [] as Array<{ title: string }>);
vi.mock("../notice-center", () => ({
  notify: (notice: { title: string }) => notices.push(notice),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { LeadTasks } from "./lead-tasks";
import type { LeadDetail, TaskView } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown 10 (2 Nov 2026): an open task on the lead has Snooze
// beside Done, with the Tasks list's choices. Made-up people only.
const LEAD = "11111111-1111-4111-8111-111111111111";
const NOW = new Date("2026-11-02T10:00:00+05:30");
const task: TaskView = {
  task_id: "33333333-3333-4333-8333-333333333333",
  lead_id: LEAD,
  lead_name: "Ravi Kulkarni",
  kind: "call_back",
  title: "Call Ravi back",
  note: null,
  starts_at: "2026-11-02T04:30:00Z",
  ends_at: null,
  location: null,
  status: "open",
  done_at: null,
  original_due_at: "2026-11-02T04:30:00Z",
  snoozes: 0,
  rollovers: 0,
  source: "manual",
  revision: 2,
  owner_person_id: null,
  overdue: false,
  bucket: "today",
};
const detail = { lead: { lead_id: LEAD }, can_edit: true, tasks: [task] };

let host: HTMLDivElement;
let root: Root;
let asked: Array<{ url: string; body: string }> = [];
beforeEach(() => {
  notices.length = 0;
  asked = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push({ url, body: String(init?.body ?? "") });
      if (url.endsWith("/snooze"))
        return Response.json({ ...task, starts_at: "2026-11-02T05:30:00Z" });
      return Response.json({ ...detail, tasks: [] });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

it("snoozes an open task from the lead, beside Done", async () => {
  const changed = vi.fn();
  await act(async () =>
    root.render(
      <LeadTasks
        detail={detail as unknown as LeadDetail}
        onChanged={changed}
        now={() => NOW}
      />,
    ),
  );
  const later = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Later: Call Ravi back"]',
  )!;
  expect(
    host.querySelector('button[aria-label="Done: Call Ravi back"]'),
  ).not.toBeNull();
  await act(async () => later.click());
  const choices = [...document.querySelectorAll("button")].map(
    (item) => item.textContent,
  );
  expect(choices).toEqual(
    expect.arrayContaining([
      "15 minutes",
      "1 hour",
      "This evening",
      "Tomorrow",
    ]),
  );
  await act(async () =>
    [...document.querySelectorAll("button")]
      .find((item) => item.textContent === "1 hour")!
      .click(),
  );
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
  const snoozed = asked.find((call) => call.url.endsWith("/snooze"))!;
  expect(snoozed.url).toContain(`/tasks/${task.task_id}/snooze`);
  expect(JSON.parse(snoozed.body)).toMatchObject({
    choice: "1h",
    expected_revision: 2,
  });
  expect(notices.at(-1)?.title).toMatch(/^Moved to /);
  expect(changed).toHaveBeenCalledTimes(1);
});
