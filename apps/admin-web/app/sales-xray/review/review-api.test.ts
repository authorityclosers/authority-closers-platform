import { afterEach, describe, expect, it, vi } from "vitest";

import { reviewError } from "./review-api";

describe("review API boundary", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps a server bridge error terminal when the contract is unavailable", () => {
    expect(
      reviewError(
        Object.assign(
          new Error(
            "The review bridge contract is pending its server-owned DTO.",
          ),
          { retryable: false },
        ),
      ),
    ).toEqual({
      message: "The review bridge contract is pending its server-owned DTO.",
      retryable: false,
    });
  });

  it("marks unknown failures retryable so the adapter can offer recovery", () => {
    expect(reviewError(new Error("temporary upstream failure"))).toEqual({
      message: "temporary upstream failure",
      retryable: true,
    });
  });
});
