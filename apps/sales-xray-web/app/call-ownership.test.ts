import { expect, it } from "vitest";

import { ownerLabel, ownsCall } from "./call-ownership";

const me = "00000000-0000-4000-8000-000000000001";
const asha = { personId: "00000000-0000-4000-8000-000000000002", name: "Asha" };

it("lets only the call's owner change it", () => {
  // Lists read with owners carry one only where others' calls can appear.
  expect(ownsCall(undefined, me)).toBe(true);
  expect(ownsCall({ personId: me }, me)).toBe(true);
  expect(ownsCall(asha, me)).toBe(false);
  // An unconfirmed viewer owns nobody else's call.
  expect(ownsCall(asha, null)).toBe(false);
});

it("names the owner, or says You", () => {
  expect(ownerLabel({ personId: me, name: "Me Myself" }, me)).toBe("You");
  expect(ownerLabel(asha, me)).toBe("Asha");
});
