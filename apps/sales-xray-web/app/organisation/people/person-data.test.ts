import { expect, it } from "vitest";

import type { OrgActivity, OrgMember } from "../organisation-api";
import {
  findMember,
  personActivity,
  personHref,
  skillMatrix,
  skillStatus,
  weeklyTotals,
} from "./person-data";

const asha = "00000000-0000-4000-8000-0000000000a1";
const neha = "00000000-0000-4000-8000-0000000000b2";
const invite = "00000000-0000-4000-8000-0000000000c3";
const NOW = Date.parse("2026-10-11T09:00:00Z");
const DAY = 86_400_000;

const call = (id: string, owner: string, daysAgo: number, seconds = 600) => ({
  id: `00000000-0000-4000-8000-${id.padStart(12, "0")}`,
  ownerPersonId: owner,
  ownerName: owner === asha ? "Asha Menon" : "Neha Kulkarni",
  label: null,
  createdAt: new Date(NOW - daysAgo * DAY).toISOString(),
  durationSeconds: seconds,
  state: "completed",
  hasReport: true,
});

const activity: OrgActivity = {
  members: [],
  perDay: [],
  perRep: [
    {
      personId: asha,
      name: "Asha Menon",
      calls: 5,
      recordedMinutes: 52,
      reportsReady: 4,
    },
  ],
  calls: [
    call("1", asha, 1),
    call("2", neha, 2),
    call("3", asha, 20),
    call("4", asha, 0.5),
  ],
};

it("finds a person by their id or an invitation by its id", () => {
  const members = [
    { personId: asha, inviteId: null, status: "active", name: "Asha Menon" },
    { personId: null, inviteId: invite, status: "invited", name: null },
  ] as unknown as OrgMember[];
  expect(findMember(members, asha.toUpperCase())?.name).toBe("Asha Menon");
  expect(findMember(members, invite)?.status).toBe("invited");
  expect(findMember(members, neha)).toBeNull();
  expect(personHref(asha.toUpperCase())).toBe(`/organisation/people/${asha}`);
});

it("counts from the server's totals and lists only this person's calls, newest first", () => {
  const data = personActivity(activity, asha);
  expect(data.calls).toBe(5);
  expect(data.minutes).toBe(52);
  expect(data.reportsReady).toBe(4);
  expect(data.listed.map((item) => item.id.slice(-1))).toEqual(["4", "1", "3"]);
  expect(data.lastCallAt).toBe(data.listed[0].createdAt);
  // Five counted, three listed: the list is the organisation's newest 500.
  expect(data.complete).toBe(false);
  // Without a per-person row, the listed calls are all there is.
  const listedOnly = personActivity({ ...activity, perRep: [] }, neha);
  expect(listedOnly).toMatchObject({ calls: 1, minutes: 10, complete: true });
});

it("puts calls into twelve 7-day weeks ending now, oldest first", () => {
  const weeks = weeklyTotals(
    [
      call("1", asha, 1, 120),
      call("2", asha, 6.9),
      call("3", asha, 8),
      call("4", asha, 90),
    ],
    NOW,
  );
  expect(weeks).toHaveLength(12);
  expect(weeks[11]).toMatchObject({ calls: 2, minutes: 12 });
  expect(weeks[10]).toMatchObject({ calls: 1, minutes: 10 });
  expect(weeks.reduce((sum, week) => sum + week.calls, 0)).toBe(3);
});

it("lays each skill against the calls, oldest first, with gaps where a report is silent", () => {
  const rows = skillMatrix([
    {
      callId: "new",
      pattern: {
        outcome: null,
        fixFirst: null,
        skills: [{ id: "discovery", label: "Discovery", status: "observed" }],
      },
    },
    {
      callId: "old",
      pattern: {
        outcome: null,
        fixFirst: null,
        skills: [
          { id: "closing", label: "Closing", status: "partial" },
          {
            id: "discovery",
            label: "Discovery",
            status: "insufficient_evidence",
          },
        ],
      },
    },
  ]);
  expect(rows.map((row) => row.label)).toEqual(["Closing", "Discovery"]);
  expect(rows[0].cells).toEqual([
    { callId: "old", status: "partial" },
    { callId: "new", status: null },
  ]);
  expect(rows[1].cells.map((cell) => skillStatus(cell.status).label)).toEqual([
    "Need more evidence",
    "Evidence found",
  ]);
  expect(skillStatus(null).label).toBe("Not in this report");
});
