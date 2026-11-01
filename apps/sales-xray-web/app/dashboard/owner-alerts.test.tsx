// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("../notice-center", () => ({ notify }));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

import { DailySummaryDetail, OwnerAlertsDetail } from "./owner-alerts";
import { alertsOn, summaryWhen, type OwnerAlerts } from "./owner-alerts-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown 19 and 20 (1 Nov 2026): three alerts on by default,
// idle sellers offered and off; the summary at 7 PM on the days picked.
const base: OwnerAlerts = {
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
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  sent = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const body = init.body ? JSON.parse(String(init.body)) : null;
      sent.push({ method: init.method ?? "GET", path: input, body });
      if (input === "/v1/lead-desk/owner-alerts/summary/test")
        return new Response(
          JSON.stringify({ phones: 1, sent: 1, ready: true }),
        );
      if (input === "/v1/lead-desk/sla")
        return new Response(
          JSON.stringify({ on: true, minutes: 10, targets: [], ...body }),
        );
      return new Response(JSON.stringify({ ...base, ...body }));
    }),
  );
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
  )!;

it("words the summary's days and counts the alerts that reach an owner", () => {
  expect(summaryWhen([])).toBe("Off");
  expect(summaryWhen([0, 1, 2, 3, 4, 5])).toBe("7 PM · Mon–Sat");
  expect(summaryWhen([0, 1, 2, 3, 4, 5, 6])).toBe("7 PM · Every day");
  expect(summaryWhen([0, 2])).toBe("7 PM · Mon, Wed");
  expect(alertsOn(base, null)).toBe(3);
  expect(alertsOn(base, { on: true, alertManagers: false })).toBe(2);
  expect(
    alertsOn({ ...base, seller_idle: true, work_hours: false }, null),
  ).toBe(3);
});

it("saves each alert, and leaves the first to the first-call target when it is on", async () => {
  const onView = vi.fn();
  const onSla = vi.fn();
  act(() =>
    root.render(
      <OwnerAlertsDetail
        view={base}
        onView={onView}
        sla={null}
        onSla={onSla}
      />,
    ),
  );
  expect(host.textContent).toContain("An enquiry isn’t called in 15 min");
  expect(
    [...host.querySelectorAll("a")].map((link) => link.getAttribute("href")),
  ).toContain("/leads/alerts?kind=missed_call");
  await act(async () =>
    toggle("A missed call isn’t returned in 30 min").click(),
  );
  expect(sent.at(-1)).toEqual({
    method: "PUT",
    path: "/v1/lead-desk/owner-alerts",
    body: {
      first_call: true,
      missed_call: false,
      no_follow_up: true,
      seller_idle: false,
      summary_days: [],
    },
  });
  expect(onView).toHaveBeenCalled();

  const target = { on: true, minutes: 10, alertManagers: true, targets: [] };
  act(() =>
    root.render(
      <OwnerAlertsDetail
        view={base}
        onView={onView}
        sla={target}
        onSla={onSla}
      />,
    ),
  );
  expect(host.textContent).toContain("An enquiry isn’t called in 10 min");
  await act(async () => toggle("An enquiry isn’t called in 10 min").click());
  expect(sent.at(-1)).toMatchObject({
    method: "PUT",
    path: "/v1/lead-desk/sla",
    body: { on: true, minutes: 10, alertManagers: false },
  });
  expect(onSla).toHaveBeenCalled();
});

it("keeps idle sellers off until working hours are set", () => {
  act(() =>
    root.render(
      <OwnerAlertsDetail
        view={{ ...base, work_hours: false }}
        onView={() => {}}
        sla={null}
        onSla={() => {}}
      />,
    ),
  );
  expect(toggle("A seller makes no call for 45 min").disabled).toBe(true);
  expect(host.textContent).toContain("Set working hours first");
});

it("turns the summary on for the working week, and sends a test now", async () => {
  const onView = vi.fn();
  act(() => root.render(<DailySummaryDetail view={base} onView={onView} />));
  await act(async () => toggle("Send me the day’s summary at 7 PM").click());
  expect(sent.at(-1)?.body).toMatchObject({ summary_days: [0, 1, 2, 3, 4, 5] });
  const test = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Send a test now",
  )!;
  await act(async () => test.click());
  expect(sent.at(-1)).toMatchObject({
    method: "POST",
    path: "/v1/lead-desk/owner-alerts/summary/test",
  });
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "success", title: "Sent to your phone" }),
  );
  expect(host.querySelector('a[href="/leads/summary"]')).not.toBeNull();
});
