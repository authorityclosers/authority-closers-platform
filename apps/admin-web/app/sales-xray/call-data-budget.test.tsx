// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { CallDataBudget } from "./call-data-budget";
import { normalizeCallData } from "./call-data-model";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const status = (extra: Record<string, unknown>) => ({
  spent_today_inr: 150,
  daily_cap_inr: 150,
  at_cap: true,
  raise_to_inr: 300,
  fresh_hours: 2,
  ...extra,
});

function render(fast: Record<string, unknown>) {
  const settings = normalizeCallData({
    revision: 7,
    config: {
      fast: { enabled: true, daily_cap_inr: 150 },
      deep: { enabled: false, daily_cap_inr: 300 },
    },
    status: { fast: status(fast), deep: status({ at_cap: false, held: 0 }) },
  });
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<CallDataBudget settings={settings} />);
  return host;
}

it("says plainly which calls still run and which are held", () => {
  const host = render({
    waiting: 3,
    new: 3,
    held: 170,
    oldest_held_at: "2026-10-12T06:00:00Z",
  });
  const text = host.textContent ?? "";
  expect(text).toContain("3 new calls waiting");
  expect(text).toContain("170 calls held since 12 Oct");
  expect(text).toContain("Held calls never run or charge by themselves");
  expect(text).toContain("New calls wait 2 hours");
  expect(text).not.toContain("Nothing is lost");
});

it("shows no held line when nothing is held", () => {
  const host = render({
    waiting: 0,
    held: 0,
    at_cap: false,
    spent_today_inr: 20,
  });
  expect(host.querySelector("[data-held]")).toBeNull();
});
