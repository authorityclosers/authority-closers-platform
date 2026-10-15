import { expect, it } from "vitest";

import { istStamp } from "./time";

it("formats in India time whatever the machine's zone, and never throws", () => {
  // 03:35 UTC is 09:05 in India.
  expect(istStamp("2026-10-11T03:35:00Z")).toMatch(/11 Oct 2026, 9:05\s?am/i);
  expect(istStamp(new Date("2026-10-11T03:35:00Z"))).toBe(
    istStamp("2026-10-11T03:35:00Z"),
  );
  expect(istStamp(null)).toBe("—");
  expect(istStamp(undefined, "Unavailable")).toBe("Unavailable");
  expect(istStamp("not a date")).toBe("—");
});
