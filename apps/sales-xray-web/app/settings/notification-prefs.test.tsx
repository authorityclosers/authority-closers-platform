// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("../notice-center", () => ({ notify }));

import { NotificationPrefs } from "./notification-prefs";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown 26 (1 Nov 2026): one place for what reaches the phone.
const prefs = (manager: boolean) => ({
  new_enquiry: true,
  follow_up_due: true,
  missed_follow_up: true,
  team_alerts: true,
  due_lead_minutes: 0,
  quiet: true,
  working_hours: "10:30–7:00, Mon–Sat",
  manager,
  phones: 1,
});
const owner = {
  first_call: true,
  missed_call: true,
  no_follow_up: true,
  seller_idle: false,
  first_call_minutes: 15,
  first_call_by_target: false,
  work_hours: true,
  summary_days: [],
  phones: 1,
};

let host: HTMLDivElement, root: Root;
let sent: { method: string; path: string; body: unknown }[];
const serve = (manager: boolean) => {
  let mine: Record<string, unknown> = prefs(manager);
  let theirs: Record<string, unknown> = owner;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const body = init.body ? JSON.parse(String(init.body)) : null;
      sent.push({ method: init.method ?? "GET", path: input, body });
      if (input === "/v1/lead-desk/notifications/test")
        return new Response(
          JSON.stringify({ phones: 1, sent: 1, ready: true }),
        );
      if (input === "/v1/lead-desk/notifications")
        return new Response(JSON.stringify((mine = { ...mine, ...body })));
      return new Response(JSON.stringify((theirs = { ...theirs, ...body })));
    }),
  );
};
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  sent = [];
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  notify.mockClear();
});

const toggle = (label: string) =>
  host.querySelector<HTMLButtonElement>(
    `[role="switch"][aria-label="${label}"]`,
  );

it("shows a seller their own types, saves each, and times follow-ups", async () => {
  serve(false);
  await act(async () => root.render(<NotificationPrefs />));
  expect(toggle("New enquiry")).not.toBeNull();
  expect(toggle("Team alerts")).toBeNull();
  expect(toggle("Daily summary")).toBeNull();
  expect(host.textContent).toContain("Working hours: 10:30–7:00, Mon–Sat");
  await act(async () => toggle("Missed follow-up")!.click());
  expect(sent.at(-1)).toMatchObject({
    method: "PUT",
    path: "/v1/lead-desk/notifications",
    body: { missed_follow_up: false, due_lead_minutes: 0 },
  });
  const early = [...host.querySelectorAll('[role="radio"]')].find(
    (item) => item.textContent === "15 min before",
  ) as HTMLButtonElement;
  await act(async () => early.click());
  expect(sent.at(-1)?.body).toMatchObject({ due_lead_minutes: 15 });
  expect(early.getAttribute("aria-checked")).toBe("true");
});

it("gives owners team alerts and the summary, and sends a test", async () => {
  serve(true);
  await act(async () => root.render(<NotificationPrefs />));
  expect(toggle("Team alerts")).not.toBeNull();
  await act(async () => toggle("Daily summary")!.click());
  expect(sent.at(-1)).toMatchObject({
    method: "PUT",
    path: "/v1/lead-desk/owner-alerts",
    body: { summary_days: [0, 1, 2, 3, 4, 5] },
  });
  expect(host.textContent).toContain("7 PM · Mon–Sat");
  const test = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Send me a test notification",
  )!;
  await act(async () => test.click());
  expect(sent.at(-1)).toMatchObject({
    method: "POST",
    path: "/v1/lead-desk/notifications/test",
  });
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "success", title: "Sent to your phone" }),
  );
});

it("sends one test for two quick taps (the robot's 14836c51)", async () => {
  serve(false);
  await act(async () => root.render(<NotificationPrefs />));
  const test = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Send me a test notification",
  )!;
  // Both taps land before the button re-renders as "Sending…".
  await act(async () => {
    test.click();
    test.click();
  });
  const tests = sent.filter(
    (call) => call.path === "/v1/lead-desk/notifications/test",
  );
  expect(tests).toHaveLength(1);
  // Once it has answered, another tap sends again.
  const again = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Send me a test notification",
  )!;
  await act(async () => again.click());
  expect(
    sent.filter((call) => call.path === "/v1/lead-desk/notifications/test"),
  ).toHaveLength(2);
});
