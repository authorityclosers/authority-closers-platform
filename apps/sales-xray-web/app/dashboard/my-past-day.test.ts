/** Me -> Past days shows the signed-in person's own day (Codex review on PR #617). */
import { expect, it } from "vitest";

import type {
  Effort,
  SellerEffort,
  SideEffort,
} from "../performance/performance-client";
import { ownDay } from "./my-past-day";

const side = (attempted: number): SideEffort =>
  ({
    attempted,
    connected: attempted,
    talk_seconds: 60 * attempted,
    reached: attempted,
  }) as SideEffort;

const seller = (person_id: string, attempted: number): SellerEffort =>
  ({
    person_id,
    name: person_id,
    inbound: side(attempted),
    cold: side(0),
  }) as unknown as SellerEffort;

const effort = (team: boolean, sellers: SellerEffort[]): Effort =>
  ({ team, sellers, inbound: side(99), cold: side(0) }) as unknown as Effort;

it("takes a seller's own read as it is", () => {
  expect(
    ownDay(effort(false, [seller("me", 4)]), "inbound", "me").attempted,
  ).toBe(4);
});

it("picks the signed-in person's row from the team's read, never the first seller", () => {
  const team = effort(true, [
    seller("p1", 9),
    seller("me", 3),
    seller("p2", 7),
  ]);
  expect(ownDay(team, "inbound", "me").attempted).toBe(3);
});

it("says no calls when the team's read has no row for them", () => {
  const team = effort(true, [seller("p1", 9)]);
  expect(ownDay(team, "inbound", "me")).toEqual({
    attempted: 0,
    connected: 0,
    talk_seconds: 0,
    reached: 0,
    interested: 0,
    meetings: 0,
    won: 0,
  });
  expect(ownDay(team, "inbound", null).attempted).toBe(0);
});
