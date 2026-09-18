import { expect, it, vi } from "vitest";

const notFound = vi.hoisted(() =>
  vi.fn(() => {
    throw new Error("not-found");
  }),
);

vi.mock("next/navigation", () => ({ notFound }));

import AcademyAssignedReviewPage from "./[assignmentId]/page";
import ReviewInvitationPage from "./invite/page";

it("returns not found for the legacy learner assignment route", async () => {
  await expect(
    AcademyAssignedReviewPage({
      params: Promise.resolve({ assignmentId: "assignment-id" }),
    }),
  ).rejects.toThrow("not-found");
  expect(notFound).toHaveBeenCalledOnce();
});

it("returns not found for the legacy learner invitation route", () => {
  expect(() => ReviewInvitationPage()).toThrow("not-found");
  expect(notFound).toHaveBeenCalledTimes(2);
});
