import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { LeadLine, whyLine } from "./desk-view";
import type { LeadRow } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const now = new Date("2026-10-18T06:00:00Z");

const row = (extra: Partial<LeadRow> = {}): LeadRow => ({
  lead_id: "11111111-1111-4111-8111-111111111111",
  revision: 2,
  name: "Asha Rao",
  company: null,
  city: null,
  language: null,
  interest: "Home loan",
  phone_last4: "1111",
  stage: "follow_up",
  stage_label: "Follow-up",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "Follow-up",
  why_kind: "open",
  next_action_at: null,
  created_at: "2026-10-17T06:00:00Z",
  attempts: 1,
  calls: 1,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...extra,
});

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("says a lead called and is waiting for a call back", () => {
  expect(
    whyLine(row({ missed_at: "2026-10-18T05:50:00Z", missed_calls: 1 }), now),
  ).toBe("Missed call 10 min ago · call back");
  expect(
    whyLine(row({ missed_at: "2026-10-18T04:00:00Z", missed_calls: 3 }), now),
  ).toBe("Missed call 2 h ago · 3 calls · call back");
  expect(whyLine(row(), now)).toBe("Follow-up");
});

it("shows a missed call in red on the desk", async () => {
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row({ missed_at: new Date().toISOString(), missed_calls: 1 })}
          onOpen={() => undefined}
        />
      </ul>,
    ),
  );
  const why = host.querySelector("[data-tone]")!;
  expect(why.getAttribute("data-tone")).toBe("bad");
  expect(why.textContent).toContain("Missed call just now");
});
