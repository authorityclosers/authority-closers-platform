import { describe, expect, it } from "vitest";

import {
  clockText,
  missedLead,
  phoneMissedIt,
  stepsLeft,
} from "./missed-alert-rules";
import type { UpdateNotification } from "./updates-client";

const NOW = Date.parse("2026-11-17T14:20:00Z");

function line(over: Partial<UpdateNotification>): UpdateNotification {
  return {
    id: "n1",
    kind: "lead_new",
    title: "New lead: Rohan Deshmukh",
    body: "Meta ad · No one has it yet. Call now or give it to a seller.",
    href: "/leads?lead=00000000-0000-4000-8000-000000000001",
    urgent: true,
    created_at: "2026-11-17T14:12:00Z",
    read: false,
    ...over,
  };
}

describe("missedLead", () => {
  it("names the newest unread lead line with its source and time", () => {
    const found = missedLead(
      [
        line({
          id: "old",
          created_at: "2026-11-17T10:00:00Z",
          title: "New lead: Neha Joshi",
        }),
        line({}),
      ],
      NOW,
      new Set(),
    );
    expect(found).toEqual({
      lineId: "n1",
      leadId: "00000000-0000-4000-8000-000000000001",
      name: "Rohan Deshmukh",
      detail: "Meta ad · 7:42 PM",
      href: "/leads?lead=00000000-0000-4000-8000-000000000001",
    });
  });

  it("reads a lead given to this seller too", () => {
    const found = missedLead(
      [
        line({
          kind: "lead_assigned",
          title: "Sanjay Patil is your lead now",
          body: "New from Meta ad. Picked automatically because you had the fewest open leads.",
        }),
      ],
      NOW,
      new Set(),
    );
    expect(found?.name).toBe("Sanjay Patil");
    expect(found?.detail).toBe("Meta ad · 7:42 PM");
  });

  it("never nags twice, and skips read, old and other lines", () => {
    expect(missedLead([line({})], NOW, new Set(["n1"]))).toBeNull();
    expect(missedLead([line({ read: true })], NOW, new Set())).toBeNull();
    expect(
      missedLead(
        [line({ created_at: "2026-11-16T10:00:00Z" })],
        NOW,
        new Set(),
      ),
    ).toBeNull();
    expect(
      missedLead(
        [line({ kind: "report_ready", href: "/reports/1" })],
        NOW,
        new Set(),
      ),
    ).toBeNull();
  });
});

describe("the phone", () => {
  const all = {
    notifications: true,
    callAccess: true,
    audio: true,
    battery: true,
  };

  it("shows the card only where notifications are off", () => {
    expect(phoneMissedIt(null)).toBe(false);
    expect(phoneMissedIt(all)).toBe(false);
    expect(phoneMissedIt({ ...all, notifications: false })).toBe(true);
  });

  it("asks only for what is missing, in order", () => {
    expect(
      stepsLeft({
        notifications: false,
        callAccess: true,
        audio: false,
        battery: false,
      }),
    ).toEqual(["notifications", "audio", "battery"]);
    expect(stepsLeft(all)).toEqual([]);
  });

  it("says the time as the phone alert does", () => {
    expect(clockText("2026-11-17T14:12:00Z")).toBe("7:42 PM");
    expect(clockText("2026-11-17T03:35:00Z")).toBe("9:05 AM");
  });
});
