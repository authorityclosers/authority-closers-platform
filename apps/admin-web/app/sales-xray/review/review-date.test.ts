import { describe, expect, it } from "vitest";
import { localReviewDate, reviewDateEpoch } from "./review-date";

describe("review expiry input", () => {
  it("round-trips a local calendar selection without treating it as UTC", () => {
    const epoch = Math.floor(new Date(2026, 8, 20, 17, 45).getTime() / 1000);
    expect(localReviewDate(epoch)).toBe("2026-09-20T17:45");
    expect(reviewDateEpoch("2026-09-20T17:45")).toBe(epoch);
  });
  it("rejects malformed and normalized dates", () => {
    for (const value of [
      "",
      "1789419600",
      "2026-02-30T12:00",
      "2026-13-10T12:00",
      "2026-09-20T17:45Z",
    ])
      expect(Number.isNaN(reviewDateEpoch(value))).toBe(true);
  });
});
