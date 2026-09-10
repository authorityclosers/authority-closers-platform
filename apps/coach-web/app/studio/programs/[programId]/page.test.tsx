import { expect, it, vi } from "vitest";
import { StudioProgram } from "@ac/operations-web/studio";
import Course from "./page";

const mocks = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("not-found");
  }),
  studioProgram: vi.fn(() => null),
}));

vi.mock("next/navigation", () => ({ notFound: mocks.notFound }));
vi.mock("@ac/operations-web/studio", () => ({
  StudioProgram: mocks.studioProgram,
}));

it("canonicalizes a mixed-case UUID before rendering StudioProgram", async () => {
  const mixedCaseId = "A1B2C3D4-E5F6-4A78-8B90-C1D2E3F4A5B6";
  const page = await Course({
    params: Promise.resolve({ programId: mixedCaseId }),
  });

  expect(page.props.children.type).toBe(StudioProgram);
  expect(page.props.children.props).toEqual({
    programId: mixedCaseId.toLowerCase(),
  });
  expect(mocks.notFound).not.toHaveBeenCalled();
});

it("calls notFound for an invalid UUID", async () => {
  await expect(
    Course({ params: Promise.resolve({ programId: "not-a-uuid" }) }),
  ).rejects.toThrow("not-found");

  expect(mocks.notFound).toHaveBeenCalledOnce();
  expect(mocks.studioProgram).not.toHaveBeenCalled();
});
