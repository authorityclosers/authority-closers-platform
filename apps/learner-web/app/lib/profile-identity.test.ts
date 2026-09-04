import { describe, expect, it } from "vitest";

import { initialsForDisplayName } from "./profile-identity";

describe("profile identity fallbacks", () => {
  it("uses the first and surname initials for multi-word names", () => {
    expect(initialsForDisplayName("  Dipak Vishwakarma Sharma ")).toBe("DS");
    expect(initialsForDisplayName("Suyash Rahegaonkar")).toBe("SR");
  });

  it("keeps single-name and empty-name fallbacks readable", () => {
    expect(initialsForDisplayName("Learner")).toBe("L");
    expect(initialsForDisplayName(" ")).toBe("AC");
  });
});
