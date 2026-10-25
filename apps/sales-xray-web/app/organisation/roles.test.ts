import { expect, it } from "vitest";

import { can, roleLabel, rolesToGive } from "./roles";

it("says what each role may do, as the server does", () => {
  expect(can("owner", "billing.pay")).toBe(true);
  expect(can("admin", "billing.pay")).toBe(false);
  expect(can("finance", "billing.pay")).toBe(true);
  expect(can("manager", "team.view")).toBe(true);
  expect(can("manager", "leads.manage")).toBe(true);
  expect(can("manager", "leads.delete")).toBe(false);
  expect(can("manager", "members.manage")).toBe(false);
  expect(can("viewer", "team.view")).toBe(true);
  expect(can("viewer", "leads.work")).toBe(false);
  expect(can("member", "team.view")).toBe(false);
  expect(can("member", "leads.work")).toBe(true);
  // Unknown roles may do nothing, including prototype names.
  for (const role of [null, undefined, "", "learner", "constructor", "OWNER"])
    expect(can(role, "team.view")).toBe(false);
});

it("names roles, and offers what owners and admins may give", () => {
  expect(roleLabel("member")).toBe("Seller");
  expect(roleLabel("manager")).toBe("Sales manager");
  expect(roleLabel("something new")).toBe("Seller");
  expect(rolesToGive(true)).toEqual([
    "admin",
    "manager",
    "member",
    "viewer",
    "finance",
  ]);
  expect(rolesToGive(false)).toEqual([
    "manager",
    "member",
    "viewer",
    "finance",
  ]);
});
