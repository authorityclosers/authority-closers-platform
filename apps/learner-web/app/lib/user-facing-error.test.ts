import { describe, expect, it } from "vitest";

import { ApiError } from "./learner-api";
import { userFacingRequestError } from "./user-facing-error";

describe("learner request errors", () => {
  it("preserves actionable client errors", () => {
    expect(
      userFacingRequestError(
        new ApiError(400, "Use a valid email address."),
        "Try again.",
      ),
    ).toBe("Use a valid email address.");
  });

  it("does not expose raw service failures", () => {
    expect(
      userFacingRequestError(
        new ApiError(500, "Internal Server Error"),
        "The profile did not finish loading. Try again.",
      ),
    ).toBe("The profile did not finish loading. Try again.");
    expect(
      userFacingRequestError(new TypeError("fetch failed"), "Retry."),
    ).toBe("Retry.");
  });
});
