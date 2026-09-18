import { describe, expect, it } from "vitest";

import {
  readReviewInvitationToken,
  reviewInvitationFragment,
  reviewInvitationHref,
  withReviewInvitationToken,
} from "./review-invitation-auth";

const token = "invite-token-" + "c".repeat(48);

describe("review invitation auth handoff", () => {
  it("keeps the token in a fragment and rejects query-style or malformed values", () => {
    const fragment = reviewInvitationFragment(token);
    expect(readReviewInvitationToken(fragment)).toBe(token);
    expect(reviewInvitationHref(token)).toBe(
      `/sales-xray/review/invite${fragment}`,
    );
    expect(withReviewInvitationToken("/login", token)).toBe(
      `/login${fragment}`,
    );
    expect(
      readReviewInvitationToken(
        `#review_invitation=${encodeURIComponent("short")}`,
      ),
    ).toBeNull();
    expect(
      readReviewInvitationToken(
        `?review_invitation=${encodeURIComponent(token)}`,
      ),
    ).toBe(token);
    expect(
      readReviewInvitationToken(`#token=${encodeURIComponent(token)}`),
    ).toBeNull();
    expect(
      readReviewInvitationToken(`#token=${encodeURIComponent(token)}`, true),
    ).toBe(token);
  });
});
